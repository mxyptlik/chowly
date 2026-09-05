"""Tenant/location and public-order WebSocket endpoints."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.events import (
    InvalidRealtimeGrant,
    RealtimeTokenCodec,
    public_order_channel,
    staff_channel,
)
from app.realtime import RedisEventBus, RealtimeRuntime


def build_realtime_runtime() -> RealtimeRuntime:
    settings = get_settings()
    return RealtimeRuntime(
        RedisEventBus(settings.redis_url, history_limit=settings.event_history_limit)
    )


def create_realtime_router(runtime: RealtimeRuntime | None = None) -> APIRouter:
    settings = get_settings()
    active_runtime = runtime or build_realtime_runtime()
    codec = RealtimeTokenCodec(settings.realtime_signing_secret)
    realtime_router = APIRouter(prefix="/api/v1/ws", tags=["realtime"])

    async def run_connection(websocket: WebSocket, channel: str, last_sequence: int) -> None:
        await active_runtime.connect(channel, websocket, last_sequence)
        unanswered_heartbeats = 0
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=settings.websocket_heartbeat_seconds,
                    )
                except TimeoutError:
                    unanswered_heartbeats += 1
                    if unanswered_heartbeats > settings.websocket_heartbeat_grace_count:
                        await websocket.close(code=1001, reason="Heartbeat timeout")
                        return
                    await websocket.send_json(
                        {"type": "system.heartbeat", "sent_at": datetime.now(UTC).isoformat()}
                    )
                    continue
                if message.get("type") == "system.pong":
                    unanswered_heartbeats = 0
        except WebSocketDisconnect:
            pass
        finally:
            await active_runtime.disconnect(channel, websocket)

    @realtime_router.websocket("/staff/tenants/{tenant_id}/locations/{location_id}")
    async def staff_events(
        websocket: WebSocket,
        tenant_id: str,
        location_id: str,
        token: str = Query(...),
        role: str = Query(..., min_length=1),
        last_sequence: int = Query(0, ge=0),
    ) -> None:
        try:
            grant = codec.decode(token)
        except InvalidRealtimeGrant:
            await websocket.close(code=4401, reason="Invalid or expired realtime grant")
            return
        if not grant.permits_staff(tenant_id, location_id, role):
            await websocket.close(code=4403, reason="Realtime scope denied")
            return
        await run_connection(websocket, staff_channel(tenant_id, location_id, role), last_sequence)

    @realtime_router.websocket("/public/orders/{order_id}")
    async def public_order_events(
        websocket: WebSocket,
        order_id: str,
        access_token: str = Query(...),
        last_sequence: int = Query(0, ge=0),
    ) -> None:
        try:
            grant = codec.decode(access_token)
        except InvalidRealtimeGrant:
            await websocket.close(code=4401, reason="Invalid or expired order access token")
            return
        if not grant.permits_order(order_id):
            await websocket.close(code=4403, reason="Order scope denied")
            return
        await run_connection(websocket, public_order_channel(order_id), last_sequence)

    return realtime_router


router = create_realtime_router()
