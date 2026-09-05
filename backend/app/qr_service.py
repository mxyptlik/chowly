"""Daily table QR lifecycle and table activity calculations."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import (
    DiningTable,
    Location,
    Order,
    OrderStatus,
    TableQrToken,
    TableVisit,
    uid,
)


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def local_calendar_date(location: Location, *, now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(ZoneInfo(location.timezone)).date()


def next_local_midnight(location: Location, issued_on: date) -> datetime:
    local_midnight = datetime.combine(
        issued_on.fromordinal(issued_on.toordinal() + 1),
        time.min,
        tzinfo=ZoneInfo(location.timezone),
    )
    return local_midnight.astimezone(UTC)


def _token_signature(row: TableQrToken, secret: str) -> str:
    message = ":".join(
        (row.id, row.tenant_id, row.location_id, row.table_id, row.issued_on.isoformat())
    ).encode("utf-8")
    return base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")


def materialize_raw_token(row: TableQrToken, *, secret: str) -> str:
    opaque_id = base64.urlsafe_b64encode(row.id.encode("ascii")).rstrip(b"=").decode("ascii")
    return f"chw_qr_{opaque_id}.{_token_signature(row, secret)}"


@dataclass(frozen=True, slots=True)
class IssuedQr:
    row: TableQrToken
    raw_token: str
    expires_at: datetime
    created: bool


def issue_table_qr(
    db: Session,
    *,
    table: DiningTable,
    location: Location,
    secret: str,
    generated_by_id: str | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> IssuedQr:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    issued_on = local_calendar_date(location, now=current)
    existing = db.scalar(
        select(TableQrToken).where(
            TableQrToken.tenant_id == table.tenant_id,
            TableQrToken.location_id == table.location_id,
            TableQrToken.table_id == table.id,
            TableQrToken.issued_on == issued_on,
            TableQrToken.invalidated_at.is_(None),
        )
    )
    if existing is not None and not force:
        return IssuedQr(
            row=existing,
            raw_token=materialize_raw_token(existing, secret=secret),
            expires_at=next_local_midnight(location, issued_on),
            created=False,
        )

    active_rows = list(
        db.scalars(
            select(TableQrToken).where(
                TableQrToken.tenant_id == table.tenant_id,
                TableQrToken.location_id == table.location_id,
                TableQrToken.table_id == table.id,
                TableQrToken.invalidated_at.is_(None),
            )
        )
    )
    for row in active_rows:
        row.invalidated_at = current
    if active_rows:
        db.flush()

    row = TableQrToken(
        id=uid(),
        tenant_id=table.tenant_id,
        location_id=table.location_id,
        table_id=table.id,
        token_hash="pending",
        issued_on=issued_on,
        issued_at=current,
        generated_by_id=generated_by_id,
    )
    raw_token = materialize_raw_token(row, secret=secret)
    row.token_hash = token_hash(raw_token)
    db.add(row)
    db.flush()
    return IssuedQr(
        row=row,
        raw_token=raw_token,
        expires_at=next_local_midnight(location, issued_on),
        created=True,
    )


def ensure_daily_table_qrs(db: Session, *, secret: str, now: datetime | None = None) -> tuple[int, int]:
    """Ensure each enabled table has today's QR without rotating existing codes.

    This is deliberately safe on restarts: it creates only missing daily tokens.
    """
    created = 0
    existing = 0
    rows = db.execute(
        select(DiningTable, Location)
        .join(Location, (Location.id == DiningTable.location_id) & (Location.tenant_id == DiningTable.tenant_id))
        .where(DiningTable.is_enabled.is_(True), Location.is_active.is_(True))
    )
    for table, location in rows:
        issued = issue_table_qr(db, table=table, location=location, secret=secret, now=now)
        if issued.created:
            created += 1
        else:
            existing += 1
    return created, existing


class InvalidTableQr(ValueError):
    def __init__(self, message: str, *, expired: bool = False) -> None:
        super().__init__(message)
        self.expired = expired


def resolve_table_qr(
    db: Session,
    raw_token: str,
    *,
    now: datetime | None = None,
) -> tuple[TableQrToken, DiningTable, Location]:
    row = db.scalar(select(TableQrToken).where(TableQrToken.token_hash == token_hash(raw_token)))
    if row is None or row.invalidated_at is not None:
        raise InvalidTableQr("This table QR code is invalid or has been refreshed.")
    table = db.scalar(
        select(DiningTable).where(
            DiningTable.id == row.table_id,
            DiningTable.tenant_id == row.tenant_id,
            DiningTable.location_id == row.location_id,
        )
    )
    location = db.scalar(
        select(Location).where(
            Location.id == row.location_id,
            Location.tenant_id == row.tenant_id,
        )
    )
    if table is None or location is None or not table.is_enabled or not location.is_active:
        raise InvalidTableQr("This table QR code is unavailable.")
    if row.issued_on != local_calendar_date(location, now=now):
        raise InvalidTableQr(
            "This table QR code has expired. Ask a waiter to refresh it.", expired=True
        )
    return row, table, location


def calculate_table_activity(db: Session, table: DiningTable) -> bool:
    active_visit = db.scalar(
        select(
            exists().where(
                TableVisit.tenant_id == table.tenant_id,
                TableVisit.location_id == table.location_id,
                TableVisit.table_id == table.id,
                TableVisit.closed_at.is_(None),
            )
        )
    )
    nonterminal_order = db.scalar(
        select(
            exists().where(
                Order.tenant_id == table.tenant_id,
                Order.location_id == table.location_id,
                Order.table_id == table.id,
                Order.status.not_in((OrderStatus.PAID, OrderStatus.CANCELLED)),
            )
        )
    )
    return bool(active_visit or nonterminal_order)


def synchronize_table_activity(db: Session, table: DiningTable) -> bool:
    table.is_active = calculate_table_activity(db, table)
    return table.is_active
