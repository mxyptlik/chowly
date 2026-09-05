"""Reservation rules independent of HTTP transport and application composition."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentStaff
from app.events import (
    EventDraft,
    EventResource,
    EventScope,
    EventType,
    ResourceKind,
    staff_channel,
    stage_domain_event,
)
from app.models import (
    AuditEvent,
    Customer,
    CustomerTenantRecord,
    DiningTable,
    Location,
    OperatingHour,
    Reservation,
    ReservationStatus,
    StaffRole,
    utc_now,
)
from app.reservation_schemas import ReservationCreateIn, ReservationPublicUpdateIn


class ReservationDomainError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


ALLOWED_TRANSITIONS: dict[ReservationStatus, frozenset[ReservationStatus]] = {
    ReservationStatus.REQUESTED: frozenset(
        {ReservationStatus.CONFIRMED, ReservationStatus.REJECTED, ReservationStatus.CANCELLED}
    ),
    ReservationStatus.CONFIRMED: frozenset(
        {ReservationStatus.CANCELLED, ReservationStatus.CHECKED_IN, ReservationStatus.SEATED}
    ),
    ReservationStatus.CHECKED_IN: frozenset({ReservationStatus.SEATED}),
    ReservationStatus.REJECTED: frozenset(),
    ReservationStatus.CANCELLED: frozenset(),
    ReservationStatus.SEATED: frozenset(),
}


def normalize_phone(value: str) -> str:
    """Accept Nigerian local or +234 format and store one canonical value."""

    digits = "".join(character for character in value if character.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        return f"+234{digits[1:]}"
    if len(digits) == 13 and digits.startswith("234"):
        return f"+{digits}"
    raise ReservationDomainError(
        "Enter an 11-digit Nigerian phone number, for example 08012345678."
    )


def _local_window(schedule_date: date, hours: OperatingHour, zone: ZoneInfo) -> tuple[datetime, datetime]:
    assert hours.opens_at is not None and hours.closes_at is not None
    opening = datetime.combine(schedule_date, hours.opens_at, tzinfo=zone)
    closing_date = schedule_date if hours.closes_at > hours.opens_at else schedule_date + timedelta(days=1)
    closing = datetime.combine(closing_date, hours.closes_at, tzinfo=zone)
    return opening, closing


def validate_requested_time(
    db: Session,
    location: Location,
    requested_at: datetime,
    *,
    now: datetime | None = None,
) -> None:
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ReservationDomainError("Reservation time must include a timezone offset.")
    current = now or datetime.now(UTC)
    if requested_at.astimezone(UTC) <= current.astimezone(UTC):
        raise ReservationDomainError("Reservation time must be in the future.")
    try:
        zone = ZoneInfo(location.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ReservationDomainError("This location's timezone is not configured correctly.", status_code=409) from exc

    local_request = requested_at.astimezone(zone)
    hours_by_weekday = {
        row.weekday: row
        for row in db.scalars(
            select(OperatingHour).where(
                OperatingHour.tenant_id == location.tenant_id,
                OperatingHour.location_id == location.id,
            )
        )
    }
    if not hours_by_weekday:
        raise ReservationDomainError("This location has not configured reservation hours.", status_code=409)

    # The previous schedule day matters for an overnight service window.
    for schedule_date in (local_request.date(), local_request.date() - timedelta(days=1)):
        hours = hours_by_weekday.get(schedule_date.weekday())
        if hours is None or hours.is_closed or hours.opens_at is None or hours.closes_at is None:
            continue
        opening, closing = _local_window(schedule_date, hours, zone)
        if opening <= local_request < closing:
            return
    raise ReservationDomainError("The requested time is outside this location's operating hours.")


def load_public_location(db: Session, location_id: str) -> Location:
    location = db.scalar(select(Location).where(Location.id == location_id, Location.is_active.is_(True)))
    if location is None:
        raise ReservationDomainError("Location not found.", status_code=404)
    return location


def load_table(
    db: Session,
    *,
    tenant_id: str,
    location_id: str,
    table_id: str,
    party_size: int,
) -> DiningTable:
    table = db.scalar(
        select(DiningTable).where(
            DiningTable.id == table_id,
            DiningTable.tenant_id == tenant_id,
            DiningTable.location_id == location_id,
            DiningTable.is_enabled.is_(True),
        )
    )
    if table is None:
        raise ReservationDomainError("Table not found.", status_code=404)
    if table.capacity < party_size:
        raise ReservationDomainError("The selected table is too small for this party.")
    return table


def _upsert_customer_visibility(
    db: Session,
    *,
    tenant_id: str,
    name: str,
    phone: str,
) -> Customer:
    customer = db.scalar(select(Customer).where(Customer.phone == phone))
    if customer is None:
        customer = Customer(name=name, phone=phone)
        db.add(customer)
        db.flush()
    visibility = db.scalar(
        select(CustomerTenantRecord).where(
            CustomerTenantRecord.tenant_id == tenant_id,
            CustomerTenantRecord.customer_id == customer.id,
        )
    )
    if visibility is None:
        visibility = CustomerTenantRecord(
            tenant_id=tenant_id,
            customer_id=customer.id,
            name_snapshot=name,
            phone_snapshot=phone,
        )
        db.add(visibility)
    else:
        visibility.name_snapshot = name
        visibility.phone_snapshot = phone
        visibility.last_seen_at = utc_now()
        visibility.purged_at = None
    return customer


def _event_payload(reservation: Reservation) -> dict[str, object | None]:
    """Intentionally excludes contact details and private request notes."""

    return {
        "status": reservation.status.value,
        "party_size": reservation.party_size,
        "requested_at": reservation.requested_at.isoformat(),
        "table_id": reservation.table_id,
    }


def stage_reservation_event(db: Session, reservation: Reservation) -> None:
    draft = EventDraft(
        type=EventType.RESERVATION_CHANGED,
        scope=EventScope(tenant_id=reservation.tenant_id, location_id=reservation.location_id),
        resource=EventResource(kind=ResourceKind.RESERVATION, id=reservation.id),
        payload=_event_payload(reservation),
    )
    # Waiters and managers have separate authenticated channels. Neither event
    # contains customer contact; clients load contact through the protected API.
    for role in (StaffRole.WAITER, StaffRole.MANAGER):
        stage_domain_event(
            db,
            staff_channel(reservation.tenant_id, reservation.location_id, role.value),
            draft.model_copy(deep=True),
        )


def issue_public_access_token() -> str:
    """Issue an opaque, high-entropy bearer token for one reservation."""

    return token_urlsafe(32)


def hash_public_access_token(access_token: str) -> str:
    """Return the storage digest without retaining the bearer token itself."""

    return sha256(access_token.encode("utf-8")).hexdigest()


def create_reservation(db: Session, payload: ReservationCreateIn) -> tuple[Reservation, str]:
    location = load_public_location(db, payload.location_id)
    validate_requested_time(db, location, payload.requested_at)
    if payload.table_id:
        load_table(
            db,
            tenant_id=location.tenant_id,
            location_id=location.id,
            table_id=payload.table_id,
            party_size=payload.party_size,
        )
    phone = normalize_phone(payload.customer_phone)
    customer = _upsert_customer_visibility(
        db,
        tenant_id=location.tenant_id,
        name=payload.customer_name,
        phone=phone,
    )
    access_token = issue_public_access_token()
    reservation = Reservation(
        tenant_id=location.tenant_id,
        location_id=location.id,
        table_id=payload.table_id,
        customer_id=customer.id,
        customer_name=payload.customer_name,
        customer_phone=phone,
        public_access_token_hash=hash_public_access_token(access_token),
        party_size=payload.party_size,
        requested_at=payload.requested_at.astimezone(UTC),
        notes=payload.note,
        status=ReservationStatus.REQUESTED,
    )
    db.add(reservation)
    db.flush()
    stage_reservation_event(db, reservation)
    return reservation, access_token


def public_reservation_by_access_token(db: Session, access_token: str) -> Reservation:
    """Find a reservation by its opaque public bearer token only.

    This deliberately provides the same not-found result for malformed and
    unknown tokens so callers cannot probe reservation IDs or contact details.
    """

    if not access_token or len(access_token) > 255:
        raise ReservationDomainError("Reservation not found.", status_code=404)
    reservation = db.scalar(
        select(Reservation).where(
            Reservation.public_access_token_hash == hash_public_access_token(access_token)
        )
    )
    if reservation is None:
        raise ReservationDomainError("Reservation not found.", status_code=404)
    return reservation


def _customer_policy(location: Location, reservation: Reservation, *, cancellation: bool) -> None:
    enabled = location.customer_cancellations_enabled if cancellation else location.customer_edits_enabled
    cutoff = location.customer_cancellation_cutoff_minutes if cancellation else location.customer_edit_cutoff_minutes
    if not enabled:
        raise ReservationDomainError("This restaurant does not allow customer changes online.", status_code=409)
    # PostgreSQL returns the timezone-aware value we persist.  SQLite (used by
    # focused tests/local fallback) returns the same UTC instant without its
    # tzinfo, so normalise it before enforcing a time-based policy.
    requested_at = reservation.requested_at
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        requested_at = requested_at.replace(tzinfo=UTC)
    if requested_at <= utc_now() + timedelta(minutes=cutoff):
        raise ReservationDomainError("This reservation is inside the restaurant's change cutoff.", status_code=409)
    if reservation.status not in {ReservationStatus.REQUESTED, ReservationStatus.CONFIRMED}:
        raise ReservationDomainError("This reservation can no longer be changed.", status_code=409)


def update_public_reservation(db: Session, reservation: Reservation, payload: ReservationPublicUpdateIn) -> Reservation:
    location = load_public_location(db, reservation.location_id)
    _customer_policy(location, reservation, cancellation=False)
    validate_requested_time(db, location, payload.requested_at)
    before = {"party_size": reservation.party_size, "requested_at": reservation.requested_at.isoformat(), "status": reservation.status.value}
    reservation.party_size = payload.party_size
    reservation.requested_at = payload.requested_at.astimezone(UTC)
    reservation.status = ReservationStatus.REQUESTED
    reservation.confirmed_at = None
    reservation.confirmed_by_id = None
    db.add(AuditEvent(tenant_id=reservation.tenant_id, location_id=reservation.location_id, actor_id=None, event_type="RESERVATION_CUSTOMER_UPDATED", subject_type="RESERVATION", subject_id=reservation.id, detail="Customer updated reservation", before_data=before, after_data={"party_size": reservation.party_size, "requested_at": reservation.requested_at.isoformat(), "status": reservation.status.value}))
    db.flush(); stage_reservation_event(db, reservation); return reservation


def cancel_public_reservation(db: Session, reservation: Reservation) -> Reservation:
    location = load_public_location(db, reservation.location_id)
    _customer_policy(location, reservation, cancellation=True)
    before = {"status": reservation.status.value}
    reservation.status = ReservationStatus.CANCELLED
    db.add(AuditEvent(tenant_id=reservation.tenant_id, location_id=reservation.location_id, actor_id=None, event_type="RESERVATION_CUSTOMER_CANCELLED", subject_type="RESERVATION", subject_id=reservation.id, detail="Customer cancelled reservation", before_data=before, after_data={"status": reservation.status.value}))
    db.flush(); stage_reservation_event(db, reservation); return reservation


def issue_qr_pass(reservation: Reservation) -> str:
    token = issue_public_access_token()
    reservation.qr_pass_token_hash = hash_public_access_token(token)
    return token


def reservation_by_qr_pass(db: Session, token: str, current: CurrentStaff) -> Reservation:
    reservation = db.scalar(select(Reservation).where(Reservation.qr_pass_token_hash == hash_public_access_token(token)))
    if reservation is None or current.tenant_id != reservation.tenant_id or reservation.location_id not in current.location_ids:
        raise ReservationDomainError("Reservation pass not found.", status_code=404)
    return reservation


def check_in_reservation(db: Session, reservation: Reservation, current: CurrentStaff) -> Reservation:
    if reservation.status != ReservationStatus.CONFIRMED:
        raise ReservationDomainError("Only confirmed reservations can be checked in.", status_code=409)
    reservation.status = ReservationStatus.CHECKED_IN
    reservation.checked_in_at = utc_now(); reservation.checked_in_by_id = current.staff_id
    db.add(AuditEvent(tenant_id=reservation.tenant_id, location_id=reservation.location_id, actor_id=current.staff_id, event_type="RESERVATION_CHECKED_IN", subject_type="RESERVATION", subject_id=reservation.id, detail="QR pass verified by staff", before_data={"status":"CONFIRMED"}, after_data={"status":"CHECKED_IN"}))
    db.flush(); stage_reservation_event(db, reservation); return reservation


def scoped_reservation(db: Session, reservation_id: str, current: CurrentStaff) -> Reservation:
    if current.tenant_id is None:
        raise ReservationDomainError("Reservation not found.", status_code=404)
    reservation = db.scalar(
        select(Reservation).where(
            Reservation.id == reservation_id,
            Reservation.tenant_id == current.tenant_id,
            Reservation.location_id.in_(current.location_ids),
        )
    )
    if reservation is None:
        raise ReservationDomainError("Reservation not found.", status_code=404)
    return reservation


def list_scoped_reservations(
    db: Session,
    current: CurrentStaff,
    *,
    location_id: str,
    status: ReservationStatus | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> list[Reservation]:
    if location_id not in current.location_ids or current.tenant_id is None:
        raise ReservationDomainError("Location not found.", status_code=404)
    query = select(Reservation).where(
        Reservation.tenant_id == current.tenant_id,
        Reservation.location_id == location_id,
    )
    if status is not None:
        query = query.where(Reservation.status == status)
    if starts_at is not None:
        query = query.where(Reservation.requested_at >= starts_at)
    if ends_at is not None:
        query = query.where(Reservation.requested_at < ends_at)
    return list(db.scalars(query.order_by(Reservation.requested_at, Reservation.created_at).limit(500)))


def transition_reservation(
    db: Session,
    reservation: Reservation,
    current: CurrentStaff,
    *,
    target: ReservationStatus,
    table_id: str | None = None,
    reason_or_note: str | None = None,
    now: datetime | None = None,
) -> Reservation:
    if target not in ALLOWED_TRANSITIONS[reservation.status]:
        raise ReservationDomainError(
            f"A {reservation.status.value.lower()} reservation cannot transition to {target.value.lower()}.",
            status_code=409,
        )
    timestamp = now or utc_now()
    assigned_table_id = table_id if table_id is not None else reservation.table_id
    if target == ReservationStatus.SEATED and assigned_table_id is None:
        raise ReservationDomainError("Assign a table before seating this reservation.")
    if assigned_table_id is not None:
        load_table(
            db,
            tenant_id=reservation.tenant_id,
            location_id=reservation.location_id,
            table_id=assigned_table_id,
            party_size=reservation.party_size,
        )

    before = {
        "status": reservation.status.value,
        "table_id": reservation.table_id,
        "confirmed_by_id": reservation.confirmed_by_id,
        "confirmed_at": reservation.confirmed_at.isoformat() if reservation.confirmed_at else None,
    }
    reservation.status = target
    reservation.table_id = assigned_table_id
    reservation.updated_at = timestamp
    if target == ReservationStatus.CONFIRMED:
        reservation.confirmed_by_id = current.staff_id
        reservation.confirmed_at = timestamp
    after = {
        "status": reservation.status.value,
        "table_id": reservation.table_id,
        "confirmed_by_id": reservation.confirmed_by_id,
        "confirmed_at": reservation.confirmed_at.isoformat() if reservation.confirmed_at else None,
    }
    db.add(
        AuditEvent(
            tenant_id=reservation.tenant_id,
            location_id=reservation.location_id,
            actor_id=current.staff_id,
            event_type=f"RESERVATION_{target.value}",
            subject_type="RESERVATION",
            subject_id=reservation.id,
            detail=reason_or_note or "",
            before_data=before,
            after_data=after,
        )
    )
    db.flush()
    stage_reservation_event(db, reservation)
    return reservation


def public_payload(reservation: Reservation) -> dict[str, object]:
    return {
        "id": reservation.id,
        "location_id": reservation.location_id,
        "table_id": reservation.table_id,
        "party_size": reservation.party_size,
        "requested_at": reservation.requested_at,
        "status": reservation.status,
        "created_at": reservation.created_at,
    }


def public_created_payload(reservation: Reservation, access_token: str) -> dict[str, object]:
    """Return the public reservation snapshot plus its one-time bearer token."""

    return {**public_payload(reservation), "access_token": access_token}


def staff_payload(reservation: Reservation) -> dict[str, object]:
    return {
        **public_payload(reservation),
        "contact": {"name": reservation.customer_name, "phone": reservation.customer_phone},
        "note": reservation.notes,
        "confirmed_by_id": reservation.confirmed_by_id,
        "confirmed_at": reservation.confirmed_at,
        "updated_at": reservation.updated_at,
    }
