"""Versioned domain events and post-commit publication helpers.

The realtime grant codec is deliberately small and dependency-free.  P02 may
issue these grants after authenticating a staff session; a grant is not itself
a staff login session.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


EVENT_VERSION = "1.0"
SESSION_EVENT_KEY = "chowly.pending_domain_events"
STAFF_REALTIME_ROLES = frozenset(
    {"PLATFORM_ADMIN", "TENANT_OWNER", "MANAGER", "WAITER", "CHEF", "BARTENDER"}
)


class EventType(StrEnum):
    ORDER_CHANGED = "order.changed"
    ORDER_LINE_CHANGED = "order_line.changed"
    TABLE_CHANGED = "table.changed"
    MENU_AVAILABILITY_CHANGED = "menu_availability.changed"
    RESERVATION_CHANGED = "reservation.changed"
    COMPLAINT_CHANGED = "complaint.changed"
    PAYMENT_CHANGED = "payment.changed"
    RECEIPT_CHANGED = "receipt.changed"


class ResourceKind(StrEnum):
    ORDER = "order"
    ORDER_LINE = "order_line"
    TABLE = "table"
    MENU_AVAILABILITY = "menu_availability"
    RESERVATION = "reservation"
    COMPLAINT = "complaint"
    PAYMENT = "payment"
    RECEIPT = "receipt"


EVENT_RESOURCE: dict[EventType, ResourceKind] = {
    EventType.ORDER_CHANGED: ResourceKind.ORDER,
    EventType.ORDER_LINE_CHANGED: ResourceKind.ORDER_LINE,
    EventType.TABLE_CHANGED: ResourceKind.TABLE,
    EventType.MENU_AVAILABILITY_CHANGED: ResourceKind.MENU_AVAILABILITY,
    EventType.RESERVATION_CHANGED: ResourceKind.RESERVATION,
    EventType.COMPLAINT_CHANGED: ResourceKind.COMPLAINT,
    EventType.PAYMENT_CHANGED: ResourceKind.PAYMENT,
    EventType.RECEIPT_CHANGED: ResourceKind.RECEIPT,
}


class EventScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str | None = None
    location_id: str | None = None
    order_id: str | None = None

    @model_validator(mode="after")
    def validate_hierarchy(self) -> "EventScope":
        if self.location_id and not self.tenant_id:
            raise ValueError("A location-scoped event must include tenant_id.")
        if not (self.tenant_id or self.order_id):
            raise ValueError("An event must be tenant- or order-scoped.")
        return self


class EventResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ResourceKind
    id: str


class EventEnvelope(BaseModel):
    """The only application-event shape sent over realtime channels."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"] = EVENT_VERSION
    id: str = Field(default_factory=lambda: str(uuid4()))
    sequence: int = Field(ge=1)
    type: EventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scope: EventScope
    resource: EventResource
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def resource_matches_type(self) -> "EventEnvelope":
        if EVENT_RESOURCE[self.type] != self.resource.kind:
            raise ValueError("Event resource kind does not match event type.")
        return self


class EventDraft(BaseModel):
    """A domain event before its channel-local sequence is allocated."""

    model_config = ConfigDict(extra="forbid")

    type: EventType
    scope: EventScope
    resource: EventResource
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def resource_matches_type(self) -> "EventDraft":
        if EVENT_RESOURCE[self.type] != self.resource.kind:
            raise ValueError("Event resource kind does not match event type.")
        return self

    def envelope(self, sequence: int) -> EventEnvelope:
        return EventEnvelope(
            sequence=sequence,
            type=self.type,
            occurred_at=self.occurred_at,
            scope=self.scope,
            resource=self.resource,
            payload=self.payload,
        )


def staff_channel(tenant_id: str, location_id: str, role: str) -> str:
    """Return a role-partitioned channel to prevent privileged event leakage."""

    return f"staff:{tenant_id}:{location_id}:{role.strip().upper()}"


def public_order_channel(order_id: str) -> str:
    return f"public:order:{order_id}"


class RealtimeGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["staff", "public_order"]
    expires_at: int
    tenant_id: str | None = None
    location_ids: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    order_id: str | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "RealtimeGrant":
        if self.kind == "staff":
            if not self.tenant_id or not self.location_ids or not self.roles:
                raise ValueError("Staff grants require tenant, location, and role scopes.")
            if self.order_id:
                raise ValueError("Staff grants cannot contain a public order scope.")
            normalized_roles = {role.strip().upper() for role in self.roles}
            if not normalized_roles.issubset(STAFF_REALTIME_ROLES):
                raise ValueError("Staff grant contains an unknown role.")
            self.roles = sorted(normalized_roles)
        elif not self.order_id or self.tenant_id or self.location_ids or self.roles:
            raise ValueError("Public grants may contain only an order scope.")
        return self

    def permits_staff(self, tenant_id: str, location_id: str, role: str) -> bool:
        return (
            self.kind == "staff"
            and self.tenant_id == tenant_id
            and location_id in self.location_ids
            and role.strip().upper() in self.roles
        )

    def permits_order(self, order_id: str) -> bool:
        return self.kind == "public_order" and self.order_id == order_id


class InvalidRealtimeGrant(ValueError):
    pass


class RealtimeTokenCodec:
    """Signs short-lived scoped grants with HMAC-SHA256."""

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("Realtime signing secret must be at least 32 characters.")
        self._secret = secret.encode("utf-8")

    @staticmethod
    def _encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(encoded: str) -> bytes:
        """Decode only the canonical unpadded URL-safe base64 representation.

        A lenient decoder accepts alternate final characters whose unused pad bits
        decode to the same bytes.  For a signed token that would let a mutated
        token retain a valid HMAC, so reject anything that cannot round-trip to
        the exact compact form issued by :meth:`_encode`.
        """

        try:
            raw = base64.b64decode(
                (encoded + "=" * (-len(encoded) % 4)).encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise ValueError("Malformed URL-safe base64.") from exc
        if RealtimeTokenCodec._encode(raw) != encoded:
            raise ValueError("Non-canonical URL-safe base64.")
        return raw

    def encode(self, grant: RealtimeGrant) -> str:
        payload = grant.model_dump_json().encode("utf-8")
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{self._encode(payload)}.{self._encode(signature)}"

    def decode(self, token: str, *, now: datetime | None = None) -> RealtimeGrant:
        try:
            payload_part, signature_part = token.split(".", maxsplit=1)
            payload = self._decode(payload_part)
            supplied = self._decode(signature_part)
        except (ValueError, TypeError) as exc:
            raise InvalidRealtimeGrant("Malformed realtime grant.") from exc
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not secrets.compare_digest(supplied, expected):
            raise InvalidRealtimeGrant("Invalid realtime grant signature.")
        try:
            grant = RealtimeGrant.model_validate_json(payload)
        except Exception as exc:
            raise InvalidRealtimeGrant("Invalid realtime grant payload.") from exc
        current = int((now or datetime.now(UTC)).timestamp())
        if grant.expires_at <= current:
            raise InvalidRealtimeGrant("Realtime grant has expired.")
        return grant


class EventBus(Protocol):
    async def publish(self, channel: str, draft: EventDraft) -> EventEnvelope: ...


@dataclass(slots=True)
class PendingEvent:
    channel: str
    draft: EventDraft


def stage_domain_event(session: Any, channel: str, draft: EventDraft) -> None:
    """Stage an event on a SQLAlchemy-like session; never publishes immediately."""

    session.info.setdefault(SESSION_EVENT_KEY, []).append(PendingEvent(channel, draft))


def discard_staged_events(session: Any) -> None:
    session.info.pop(SESSION_EVENT_KEY, None)


async def commit_and_publish(session: Any, bus: EventBus) -> list[EventEnvelope]:
    """Commit first and publish only when the commit succeeds.

    Callers should use this instead of ``session.commit`` whenever events were
    staged with :func:`stage_domain_event`.
    """

    pending: list[PendingEvent] = list(session.info.get(SESSION_EVENT_KEY, []))
    try:
        session.commit()
    except Exception:
        discard_staged_events(session)
        raise
    discard_staged_events(session)
    return [await bus.publish(item.channel, item.draft) for item in pending]


def canonical_event_json(envelope: EventEnvelope) -> str:
    return json.dumps(envelope.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
