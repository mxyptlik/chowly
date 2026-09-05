"""Realtime connection registry and Redis/in-memory event buses."""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from redis.asyncio import Redis

from app.events import EventDraft, EventEnvelope, canonical_event_json


EventCallback = Callable[[EventEnvelope], Awaitable[None]]


class RealtimeBus(Protocol):
    async def publish(self, channel: str, draft: EventDraft) -> EventEnvelope: ...
    async def replay(self, channel: str, after_sequence: int) -> list[EventEnvelope]: ...
    async def subscribe(self, channel: str, callback: EventCallback) -> None: ...
    async def unsubscribe(self, channel: str, callback: EventCallback) -> None: ...
    async def close(self) -> None: ...


class InMemoryEventBus:
    """Deterministic bus for tests and local fallback; sequences are per channel."""

    def __init__(self, history_limit: int = 500) -> None:
        self._history_limit = history_limit
        self._sequences: dict[str, int] = defaultdict(int)
        self._history: dict[str, list[EventEnvelope]] = defaultdict(list)
        self._callbacks: dict[str, set[EventCallback]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, draft: EventDraft) -> EventEnvelope:
        async with self._lock:
            self._sequences[channel] += 1
            envelope = draft.envelope(self._sequences[channel])
            self._history[channel].append(envelope)
            self._history[channel] = self._history[channel][-self._history_limit :]
            callbacks = tuple(self._callbacks[channel])
        if callbacks:
            await asyncio.gather(*(callback(envelope) for callback in callbacks))
        return envelope

    async def replay(self, channel: str, after_sequence: int) -> list[EventEnvelope]:
        async with self._lock:
            return [event for event in self._history[channel] if event.sequence > after_sequence]

    async def subscribe(self, channel: str, callback: EventCallback) -> None:
        async with self._lock:
            self._callbacks[channel].add(callback)

    async def unsubscribe(self, channel: str, callback: EventCallback) -> None:
        async with self._lock:
            self._callbacks[channel].discard(callback)
            if not self._callbacks[channel]:
                self._callbacks.pop(channel, None)

    async def close(self) -> None:
        async with self._lock:
            self._callbacks.clear()


class RedisEventBus:
    """Redis Streams provide replay; Redis pub/sub provides low-latency fan-out."""

    def __init__(self, redis_url: str, *, prefix: str = "chowly:events", history_limit: int = 500) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix
        self._history_limit = history_limit
        self._callbacks: dict[str, set[EventCallback]] = defaultdict(set)
        self._pubsub: Any | None = None
        self._listener: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def _topic(self, channel: str) -> str:
        return f"{self._prefix}:pubsub:{channel}"

    def _stream(self, channel: str) -> str:
        return f"{self._prefix}:stream:{channel}"

    def _sequence(self, channel: str) -> str:
        return f"{self._prefix}:sequence:{channel}"

    async def publish(self, channel: str, draft: EventDraft) -> EventEnvelope:
        sequence = int(await self._redis.incr(self._sequence(channel)))
        envelope = draft.envelope(sequence)
        encoded = canonical_event_json(envelope)
        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.xadd(
                self._stream(channel),
                {"sequence": str(sequence), "event": encoded},
                maxlen=self._history_limit,
                approximate=True,
            )
            pipeline.publish(self._topic(channel), encoded)
            await pipeline.execute()
        return envelope

    async def replay(self, channel: str, after_sequence: int) -> list[EventEnvelope]:
        rows = await self._redis.xrange(self._stream(channel), min="-", max="+")
        events = [EventEnvelope.model_validate_json(fields["event"]) for _, fields in rows]
        return [event for event in events if event.sequence > after_sequence]

    async def subscribe(self, channel: str, callback: EventCallback) -> None:
        async with self._lock:
            first = not self._callbacks[channel]
            self._callbacks[channel].add(callback)
            if self._pubsub is None:
                self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            if first:
                await self._pubsub.subscribe(self._topic(channel))
            if self._listener is None or self._listener.done():
                self._listener = asyncio.create_task(self._listen(), name="chowly-redis-events")

    async def unsubscribe(self, channel: str, callback: EventCallback) -> None:
        async with self._lock:
            self._callbacks[channel].discard(callback)
            if not self._callbacks[channel] and self._pubsub is not None:
                self._callbacks.pop(channel, None)
                await self._pubsub.unsubscribe(self._topic(channel))

    async def _listen(self) -> None:
        assert self._pubsub is not None
        try:
            while True:
                message = await self._pubsub.get_message(timeout=1.0)
                if message is None:
                    await asyncio.sleep(0.01)
                    continue
                topic = str(message["channel"])
                prefix = f"{self._prefix}:pubsub:"
                if not topic.startswith(prefix):
                    continue
                channel = topic[len(prefix) :]
                envelope = EventEnvelope.model_validate_json(message["data"])
                callbacks = tuple(self._callbacks.get(channel, ()))
                if callbacks:
                    await asyncio.gather(*(callback(envelope) for callback in callbacks))
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            await asyncio.gather(self._listener, return_exceptions=True)
        if self._pubsub is not None:
            result = self._pubsub.close()
            if inspect.isawaitable(result):
                await result
        await self._redis.aclose()


class ConnectionRegistry:
    """Tracks local WebSocket connections without retaining disconnected clients."""

    def __init__(self) -> None:
        self._connections: dict[str, set[Any]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, channel: str, websocket: Any) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[channel].add(websocket)

    async def disconnect(self, channel: str, websocket: Any) -> None:
        async with self._lock:
            self._connections[channel].discard(websocket)
            if not self._connections[channel]:
                self._connections.pop(channel, None)

    async def count(self, channel: str | None = None) -> int:
        async with self._lock:
            if channel is not None:
                return len(self._connections.get(channel, ()))
            return sum(len(connections) for connections in self._connections.values())

    async def broadcast(self, channel: str, envelope: EventEnvelope) -> None:
        async with self._lock:
            connections = tuple(self._connections.get(channel, ()))
        stale: list[Any] = []
        data = envelope.model_dump(mode="json")
        for websocket in connections:
            try:
                await websocket.send_json(data)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(channel, websocket)


class RealtimeRuntime:
    """Binds local connections to one shared cross-process event bus."""

    def __init__(self, bus: RealtimeBus, registry: ConnectionRegistry | None = None) -> None:
        self.bus = bus
        self.registry = registry or ConnectionRegistry()
        self._subscription_counts: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def _on_event(self, channel: str, envelope: EventEnvelope) -> None:
        await self.registry.broadcast(channel, envelope)

    def _callback(self, channel: str) -> EventCallback:
        async def receive(envelope: EventEnvelope) -> None:
            await self._on_event(channel, envelope)

        # Stable identity allows correct Redis unsubscribe bookkeeping.
        callback = receive
        setattr(callback, "_chowly_channel", channel)
        return callback

    async def connect(self, channel: str, websocket: Any, after_sequence: int = 0) -> None:
        async with self._lock:
            callback = getattr(self, "_callbacks", {}).get(channel) if hasattr(self, "_callbacks") else None
            if callback is None:
                if not hasattr(self, "_callbacks"):
                    self._callbacks: dict[str, EventCallback] = {}
                callback = self._callback(channel)
                self._callbacks[channel] = callback
                await self.bus.subscribe(channel, callback)
            self._subscription_counts[channel] += 1
        try:
            await self.registry.connect(channel, websocket)
            # Connections are registered before replay. A client must deduplicate by
            # sequence, which closes the replay/live race without losing an event.
            for envelope in await self.bus.replay(channel, after_sequence):
                await websocket.send_json(envelope.model_dump(mode="json"))
        except Exception:
            await self.disconnect(channel, websocket)
            raise

    async def disconnect(self, channel: str, websocket: Any) -> None:
        await self.registry.disconnect(channel, websocket)
        async with self._lock:
            self._subscription_counts[channel] = max(0, self._subscription_counts[channel] - 1)
            if self._subscription_counts[channel] == 0:
                self._subscription_counts.pop(channel, None)
                callback = self._callbacks.pop(channel)
                await self.bus.unsubscribe(channel, callback)

    async def close(self) -> None:
        await self.bus.close()
