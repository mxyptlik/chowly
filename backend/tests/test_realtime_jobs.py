from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, "backend")

from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.events import (
    EVENT_RESOURCE,
    EventDraft,
    EventResource,
    EventScope,
    EventType,
    InvalidRealtimeGrant,
    RealtimeGrant,
    RealtimeTokenCodec,
    commit_and_publish,
    public_order_channel,
    staff_channel,
    stage_domain_event,
)
from app.realtime import InMemoryEventBus, RealtimeRuntime
from app.routers.realtime import create_realtime_router
from app.core.config import get_settings
from app.tasks import cleanup_tenant_retention, send_receipt_email


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class FakeSession:
    def __init__(self, fail_commit: bool = False) -> None:
        self.info: dict = {}
        self.fail_commit = fail_commit
        self.committed = False

    def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("database rejected transaction")
        self.committed = True


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def hget(self, key: str, field: str):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key: str, mapping: dict[str, str]):
        self.hashes.setdefault(key, {}).update({name: str(value) for name, value in mapping.items()})

    def hincrby(self, key: str, field: str, amount: int) -> int:
        current = int(self.hashes.setdefault(key, {}).get(field, "0")) + amount
        self.hashes[key][field] = str(current)
        return current

    def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds


def order_draft(order_id: str, tenant_id: str = "tenant-a", location_id: str = "location-a") -> EventDraft:
    return EventDraft(
        type=EventType.ORDER_CHANGED,
        scope=EventScope(tenant_id=tenant_id, location_id=location_id, order_id=order_id),
        resource=EventResource(kind="order", id=order_id),
        payload={"status": "PREPARING"},
    )


class EventContractTests(unittest.TestCase):
    def test_every_required_resource_has_a_versioned_event_shape(self) -> None:
        for event_type, resource_kind in EVENT_RESOURCE.items():
            draft = EventDraft(
                type=event_type,
                scope=EventScope(tenant_id="tenant", location_id="location", order_id="order"),
                resource=EventResource(kind=resource_kind, id="resource"),
            )
            envelope = draft.envelope(1)
            self.assertEqual(envelope.version, "1.0")
            self.assertEqual(envelope.sequence, 1)
            self.assertEqual(envelope.resource.kind, resource_kind)

    def test_event_rejects_mismatched_resource_and_location_without_tenant(self) -> None:
        with self.assertRaises(ValidationError):
            EventScope(location_id="location")
        with self.assertRaises(ValidationError):
            EventDraft(
                type=EventType.ORDER_CHANGED,
                scope=EventScope(order_id="order"),
                resource=EventResource(kind="payment", id="payment"),
            )

    def test_signed_grants_enforce_expiry_tenant_location_role_and_order_scope(self) -> None:
        codec = RealtimeTokenCodec("test-secret-is-at-least-thirty-two-characters")
        expires = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
        staff = RealtimeGrant(
            kind="staff",
            tenant_id="tenant-a",
            location_ids=["location-a"],
            roles=["WAITER"],
            expires_at=expires,
        )
        decoded = codec.decode(codec.encode(staff))
        self.assertTrue(decoded.permits_staff("tenant-a", "location-a", "WAITER"))
        self.assertFalse(decoded.permits_staff("tenant-b", "location-a", "WAITER"))
        self.assertFalse(decoded.permits_staff("tenant-a", "location-b", "WAITER"))
        self.assertFalse(decoded.permits_staff("tenant-a", "location-a", "MANAGER"))

        public = RealtimeGrant(kind="public_order", order_id="order-a", expires_at=expires)
        decoded_public = codec.decode(codec.encode(public))
        self.assertTrue(decoded_public.permits_order("order-a"))
        self.assertFalse(decoded_public.permits_order("order-b"))

        token = codec.encode(public)
        with self.assertRaises(InvalidRealtimeGrant):
            codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"))
        expired = RealtimeGrant(
            kind="public_order",
            order_id="order-a",
            expires_at=int((datetime.now(UTC) - timedelta(seconds=1)).timestamp()),
        )
        with self.assertRaises(InvalidRealtimeGrant):
            codec.decode(codec.encode(expired))


class RealtimeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_sequences_replay_and_isolation(self) -> None:
        bus = InMemoryEventBus()
        runtime = RealtimeRuntime(bus)
        tenant_a = FakeWebSocket()
        tenant_b = FakeWebSocket()
        channel_a = staff_channel("tenant-a", "location-a", "WAITER")
        channel_b = staff_channel("tenant-b", "location-b", "WAITER")
        await runtime.connect(channel_a, tenant_a)
        await runtime.connect(channel_b, tenant_b)

        first = await bus.publish(channel_a, order_draft("order-a"))
        second = await bus.publish(channel_a, order_draft("order-a"))
        await bus.publish(channel_b, order_draft("order-b", "tenant-b", "location-b"))

        self.assertEqual([first.sequence, second.sequence], [1, 2])
        self.assertEqual([event["scope"]["tenant_id"] for event in tenant_a.sent], ["tenant-a", "tenant-a"])
        self.assertEqual([event["scope"]["tenant_id"] for event in tenant_b.sent], ["tenant-b"])

        reconnect = FakeWebSocket()
        await runtime.connect(channel_a, reconnect, after_sequence=1)
        self.assertEqual([event["sequence"] for event in reconnect.sent], [2])
        await runtime.disconnect(channel_a, reconnect)
        await runtime.disconnect(channel_a, tenant_a)
        await runtime.disconnect(channel_b, tenant_b)
        self.assertEqual(await runtime.registry.count(), 0)

    async def test_public_order_channels_do_not_leak(self) -> None:
        bus = InMemoryEventBus()
        runtime = RealtimeRuntime(bus)
        order_a = FakeWebSocket()
        order_b = FakeWebSocket()
        await runtime.connect(public_order_channel("a"), order_a)
        await runtime.connect(public_order_channel("b"), order_b)
        await bus.publish(public_order_channel("a"), order_draft("a"))
        self.assertEqual(len(order_a.sent), 1)
        self.assertEqual(order_b.sent, [])
        await runtime.disconnect(public_order_channel("a"), order_a)
        await runtime.disconnect(public_order_channel("b"), order_b)

    async def test_events_publish_only_after_successful_commit(self) -> None:
        bus = InMemoryEventBus()
        channel = staff_channel("tenant-a", "location-a", "WAITER")
        session = FakeSession()
        stage_domain_event(session, channel, order_draft("order-a"))
        self.assertEqual(await bus.replay(channel, 0), [])
        published = await commit_and_publish(session, bus)
        self.assertTrue(session.committed)
        self.assertEqual(len(published), 1)

        failed = FakeSession(fail_commit=True)
        stage_domain_event(failed, channel, order_draft("order-b"))
        with self.assertRaises(RuntimeError):
            await commit_and_publish(failed, bus)
        replay = await bus.replay(channel, 0)
        self.assertEqual([event.resource.id for event in replay], ["order-a"])
        self.assertNotIn("chowly.pending_domain_events", failed.info)


class RealtimeRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = InMemoryEventBus()
        self.runtime = RealtimeRuntime(self.bus)
        self.app = FastAPI()
        self.app.include_router(create_realtime_router(self.runtime))
        self.client = TestClient(self.app)
        self.codec = RealtimeTokenCodec(get_settings().realtime_signing_secret)
        self.expires = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())

    def test_invalid_and_cross_role_staff_grants_are_rejected(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as invalid:
            with self.client.websocket_connect(
                "/api/v1/ws/staff/tenants/tenant-a/locations/location-a?role=WAITER&token=bad"
            ):
                pass
        self.assertEqual(invalid.exception.code, 4401)

        manager_grant = self.codec.encode(
            RealtimeGrant(
                kind="staff",
                tenant_id="tenant-a",
                location_ids=["location-a"],
                roles=["MANAGER"],
                expires_at=self.expires,
            )
        )
        with self.assertRaises(WebSocketDisconnect) as forbidden:
            with self.client.websocket_connect(
                "/api/v1/ws/staff/tenants/tenant-a/locations/location-a"
                f"?role=WAITER&token={manager_grant}"
            ):
                pass
        self.assertEqual(forbidden.exception.code, 4403)

    def test_public_token_cannot_subscribe_to_another_order(self) -> None:
        token = self.codec.encode(
            RealtimeGrant(kind="public_order", order_id="order-a", expires_at=self.expires)
        )
        with self.assertRaises(WebSocketDisconnect) as forbidden:
            with self.client.websocket_connect(
                f"/api/v1/ws/public/orders/order-b?access_token={token}"
            ):
                pass
        self.assertEqual(forbidden.exception.code, 4403)

    def test_heartbeat_times_out_and_connection_is_cleaned_up(self) -> None:
        settings = get_settings()
        old_seconds = settings.websocket_heartbeat_seconds
        old_grace = settings.websocket_heartbeat_grace_count
        settings.websocket_heartbeat_seconds = 0.01
        settings.websocket_heartbeat_grace_count = 1
        token = self.codec.encode(
            RealtimeGrant(kind="public_order", order_id="order-a", expires_at=self.expires)
        )
        try:
            with self.client.websocket_connect(
                f"/api/v1/ws/public/orders/order-a?access_token={token}"
            ) as websocket:
                heartbeat = websocket.receive_json()
                self.assertEqual(heartbeat["type"], "system.heartbeat")
                with self.assertRaises(WebSocketDisconnect) as closed:
                    websocket.receive_json()
                self.assertEqual(closed.exception.code, 1001)
        finally:
            settings.websocket_heartbeat_seconds = old_seconds
            settings.websocket_heartbeat_grace_count = old_grace

        self.assertEqual(asyncio.run(self.runtime.registry.count()), 0)


class BackgroundJobTests(unittest.TestCase):
    def test_receipt_is_idempotent_and_state_is_durable(self) -> None:
        fake_redis = FakeRedis()
        deliveries: list[str] = []

        def delivery(**kwargs):
            deliveries.append(kwargs["idempotency_key"])
            return {"provider_id": "mail-1"}

        with patch("app.tasks.job_state_redis", return_value=fake_redis), patch(
            "app.tasks._receipt_delivery_adapter", side_effect=delivery
        ):
            first = send_receipt_email.fn("order-1", "Diner@Example.com")
            second = send_receipt_email.fn("order-1", "diner@example.com")

        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(len(deliveries), 1)
        state = next(iter(fake_redis.hashes.values()))
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["attempts"], "1")
        self.assertEqual(send_receipt_email.options["max_retries"], 5)

    def test_failed_job_records_attempt_and_retry_can_complete(self) -> None:
        fake_redis = FakeRedis()
        calls = 0

        def flaky(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("provider unavailable")
            return {"deleted_customers": 3}

        with patch("app.tasks.job_state_redis", return_value=fake_redis), patch(
            "app.tasks._retention_cleanup_adapter", side_effect=flaky
        ):
            with self.assertRaises(ConnectionError):
                cleanup_tenant_retention.fn("tenant-1", "2026-05-01T00:00:00+00:00")
            result = cleanup_tenant_retention.fn("tenant-1", "2026-05-01T00:00:00+00:00")

        state = next(iter(fake_redis.hashes.values()))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["attempts"], "2")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(cleanup_tenant_retention.options["max_retries"], 7)


if __name__ == "__main__":
    unittest.main()
