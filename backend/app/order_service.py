"""Canonical Chowly order state machine and audited mutation services."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.auth import CurrentStaff
from app.core.config import get_settings
from app.core.security import hash_opaque_token
from app.dependencies import assert_location_access, assert_order_operator, assert_station_access
from app.events import (
    EventDraft,
    EventResource,
    EventScope,
    EventType,
    RealtimeGrant,
    RealtimeTokenCodec,
    ResourceKind,
    public_order_channel,
    staff_channel,
    stage_domain_event,
)
from app.location_service import location_is_currently_open
from app.models import (
    AuditEvent,
    Customer,
    CustomerTenantRecord,
    DiningTable,
    LineStatus,
    Location,
    Order,
    OrderLine,
    OrderSource,
    OrderStatus,
    QueueDestination,
    ServiceMode,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    TableVisit,
    Tenant,
)
from app.order_schemas import CustomerIn, OrderLineSelectionIn
from app.pricing_service import MenuSelectionError, price_breakdown, validate_menu_selection
from app.qr_service import InvalidTableQr, resolve_table_qr, synchronize_table_activity


WAIT_TIME_SUGGESTIONS = (5, 10, 15, 30, 45)
ORDER_EVENT_ROLES = (
    StaffRole.MANAGER,
    StaffRole.WAITER,
    StaffRole.CHEF,
    StaffRole.BARTENDER,
)


class OrderDomainError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def raise_order_http(error: OrderDomainError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def normalize_customer_phone(value: str) -> str:
    """Normalize the Nigerian-first phone identity into a stable E.164-like key."""

    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("0"):
        digits = "234" + digits[1:]
    if len(digits) != 13 or not digits.startswith("234"):
        raise OrderDomainError(
            "Enter an 11-digit Nigerian phone number, for example 08012345678.",
            status_code=422,
        )
    return f"+{digits}"


def order_version(order: Order) -> str:
    value = order.updated_at or order.created_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def assert_expected_version(order: Order, expected_version: str) -> None:
    if not secrets.compare_digest(order_version(order), expected_version):
        raise OrderDomainError(
            "This order changed since it was loaded. Refresh before trying again.",
            status_code=412,
        )


def touch(order: Order, *, now: datetime | None = None) -> None:
    order.updated_at = now or datetime.now(UTC)


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def add_audit(
    db: Session,
    *,
    order: Order,
    event_type: str,
    actor_id: str | None,
    reason: str = "",
    subject_type: str = "ORDER",
    subject_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        actor_id=actor_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id or order.id,
        detail=reason.strip(),
        before_data=_json(before),
        after_data=_json(after),
        request_id=request_id,
    )
    db.add(event)
    return event


def _order_public_payload(order: Order, *, change: str) -> dict[str, Any]:
    return {
        "change": change,
        "status": order.status.value,
        "service_mode": order.service_mode.value,
        "estimated_wait_minutes": order.estimated_wait_minutes,
        "table_id": order.table_id,
        "transfer_notice": order.transfer_notice,
        "version": order_version(order),
    }


def stage_order_changed(db: Session, order: Order, *, change: str) -> None:
    draft = EventDraft(
        type=EventType.ORDER_CHANGED,
        scope=EventScope(
            tenant_id=order.tenant_id,
            location_id=order.location_id,
            order_id=order.id,
        ),
        resource=EventResource(kind=ResourceKind.ORDER, id=order.id),
        payload=_order_public_payload(order, change=change),
    )
    for role in ORDER_EVENT_ROLES:
        stage_domain_event(
            db,
            staff_channel(order.tenant_id, order.location_id, role.value),
            draft,
        )
    stage_domain_event(db, public_order_channel(order.id), draft)


def stage_line_changed(db: Session, order: Order, line: OrderLine, *, change: str) -> None:
    draft = EventDraft(
        type=EventType.ORDER_LINE_CHANGED,
        scope=EventScope(
            tenant_id=order.tenant_id,
            location_id=order.location_id,
            order_id=order.id,
        ),
        resource=EventResource(kind=ResourceKind.ORDER_LINE, id=line.id),
        payload={
            "change": change,
            "order_id": order.id,
            "line_id": line.id,
            "status": line.status.value,
            "queue_destination": line.queue_destination.value,
            "order_status": order.status.value,
            "version": order_version(order),
        },
    )
    roles = (StaffRole.MANAGER, StaffRole.WAITER)
    station = StaffRole.CHEF if line.queue_destination == QueueDestination.KITCHEN else StaffRole.BARTENDER
    for role in (*roles, station):
        stage_domain_event(
            db,
            staff_channel(order.tenant_id, order.location_id, role.value),
            draft,
        )
    # The diner receives only the aggregate order projection, never individual prep progress.
    stage_order_changed(db, order, change="preparation_progress")


def stage_table_changed(db: Session, table: DiningTable, *, change: str) -> None:
    draft = EventDraft(
        type=EventType.TABLE_CHANGED,
        scope=EventScope(tenant_id=table.tenant_id, location_id=table.location_id),
        resource=EventResource(kind=ResourceKind.TABLE, id=table.id),
        payload={"change": change, "is_active": table.is_active},
    )
    for role in (StaffRole.MANAGER, StaffRole.WAITER):
        stage_domain_event(
            db,
            staff_channel(table.tenant_id, table.location_id, role.value),
            draft,
        )


def issue_order_realtime_token(order_id: str) -> str:
    settings = get_settings()
    grant = RealtimeGrant(
        kind="public_order",
        order_id=order_id,
        expires_at=int((datetime.now(UTC) + timedelta(hours=8)).timestamp()),
    )
    return RealtimeTokenCodec(settings.realtime_signing_secret).encode(grant)


def public_order_or_404(db: Session, order_id: str, raw_token: str | None) -> Order:
    order = db.scalar(
        select(Order).options(selectinload(Order.lines)).where(Order.id == order_id)
    )
    supplied = hash_opaque_token(raw_token) if raw_token else ""
    if (
        order is None
        or not raw_token
        or not secrets.compare_digest(order.public_access_token_hash, supplied)
    ):
        raise OrderDomainError("Order link not found.", status_code=404)
    return order


def scoped_order(db: Session, order_id: str, current: CurrentStaff) -> Order:
    if current.tenant_id is None:
        raise OrderDomainError("Order not found.", status_code=404)
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.lines))
        .where(
            Order.id == order_id,
            Order.tenant_id == current.tenant_id,
            Order.location_id.in_(current.location_ids),
        )
    )
    if order is None:
        raise OrderDomainError("Order not found.", status_code=404)
    return order


def _upsert_customer(
    db: Session,
    *,
    tenant: Tenant,
    payload: CustomerIn,
    now: datetime,
) -> tuple[Customer, CustomerTenantRecord]:
    phone = normalize_customer_phone(payload.phone)
    customer = db.scalar(select(Customer).where(Customer.phone == phone))
    email = str(payload.email).strip().lower() if payload.email else None
    if customer is None:
        customer = Customer(name=payload.name.strip(), phone=phone, email=email)
        db.add(customer)
        db.flush()
    else:
        customer.name = payload.name.strip()
        if email:
            customer.email = email
        customer.updated_at = now
    record = db.scalar(
        select(CustomerTenantRecord).where(
            CustomerTenantRecord.tenant_id == tenant.id,
            CustomerTenantRecord.customer_id == customer.id,
        )
    )
    purge_after = now + timedelta(days=tenant.retention_days)
    if record is None:
        record = CustomerTenantRecord(
            tenant_id=tenant.id,
            customer_id=customer.id,
            name_snapshot=payload.name.strip(),
            phone_snapshot=phone,
            email=email,
            purge_after=purge_after,
        )
        db.add(record)
        db.flush()
    else:
        record.name_snapshot = payload.name.strip()
        record.phone_snapshot = phone
        record.email = email
        record.last_seen_at = now
        record.purge_after = purge_after
        record.purged_at = None
    return customer, record


def _snapshot_line(
    db: Session,
    *,
    order: Order,
    requested: OrderLineSelectionIn,
    location: Location,
) -> OrderLine:
    try:
        selection = validate_menu_selection(
            db,
            tenant_id=order.tenant_id,
            location_id=order.location_id,
            menu_item_id=requested.menu_item_id,
            modifier_option_ids=requested.modifier_option_ids,
        )
    except MenuSelectionError as error:
        raise OrderDomainError(
            str(error), status_code=409 if error.unavailable else 422
        ) from error
    modifiers = [
        {"id": option.id, "name": option.name, "price_delta": str(option.price_delta)}
        for option in selection.options
    ]
    amounts = price_breakdown(
        base_price=Decimal(selection.item.base_price),
        modifier_prices=[Decimal(option.price_delta) for option in selection.options],
        quantity=requested.quantity,
        vat_rate=Decimal(location.vat_rate),
        service_charge_rate=Decimal(location.service_charge_rate),
    )
    return OrderLine(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        order_id=order.id,
        menu_item_id=selection.item.id,
        quantity=requested.quantity,
        item_name_snapshot=selection.item.name,
        modifiers_snapshot=", ".join(option.name for option in selection.options),
        selected_modifiers=modifiers,
        special_instruction=requested.special_instruction.strip()
        if requested.special_instruction
        else None,
        queue_destination=selection.item.queue_destination,
        # Base unit price is snapshotted independently from modifier deltas.
        unit_price=Decimal(selection.item.base_price),
        subtotal_amount=amounts.subtotal,
        vat_amount=amounts.vat,
        service_charge_amount=amounts.service_charge,
        total_amount=amounts.total,
        status=LineStatus.PENDING,
    )


def recalculate_order(order: Order) -> None:
    active = [line for line in order.lines if line.status != LineStatus.CANCELLED]
    order.subtotal_amount = sum((Decimal(line.subtotal_amount) for line in active), Decimal("0"))
    order.vat_amount = sum((Decimal(line.vat_amount) for line in active), Decimal("0"))
    order.service_charge_amount = sum(
        (Decimal(line.service_charge_amount) for line in active), Decimal("0")
    )
    order.total_amount = sum((Decimal(line.total_amount) for line in active), Decimal("0"))


def create_order(
    db: Session,
    *,
    location: Location,
    table: DiningTable | None,
    customer_payload: CustomerIn,
    service_mode: ServiceMode,
    requested_lines: list[OrderLineSelectionIn],
    source: OrderSource,
    actor_id: str | None = None,
    owner_id: str | None = None,
    estimated_wait_minutes: int | None = None,
) -> tuple[Order, str]:
    if not location_is_currently_open(location):
        raise OrderDomainError("This location is not accepting orders right now.")
    if service_mode == ServiceMode.DINE_IN and table is None:
        raise OrderDomainError("Dine-in orders require a table.", status_code=422)
    if service_mode == ServiceMode.TAKEAWAY and table is not None:
        raise OrderDomainError("Takeaway orders cannot be assigned to a table.", status_code=422)
    tenant = db.get(Tenant, location.tenant_id)
    if tenant is None:
        raise OrderDomainError("Restaurant tenant not found.", status_code=404)
    now = datetime.now(UTC)
    customer, record = _upsert_customer(
        db, tenant=tenant, payload=customer_payload, now=now
    )
    raw_token = secrets.token_urlsafe(32)
    order = Order(
        tenant_id=location.tenant_id,
        location_id=location.id,
        table_id=table.id if table else None,
        customer_id=customer.id,
        customer_tenant_record_id=record.id,
        owner_id=owner_id,
        public_access_token_hash=hash_opaque_token(raw_token),
        source=source,
        service_mode=service_mode,
        status=OrderStatus.SUBMITTED,
        estimated_wait_minutes=estimated_wait_minutes,
        currency=location.currency,
        vat_rate_snapshot=location.vat_rate,
        service_charge_rate_snapshot=location.service_charge_rate,
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    db.flush()
    order.lines = [
        _snapshot_line(db, order=order, requested=requested, location=location)
        for requested in requested_lines
    ]
    db.flush()
    recalculate_order(order)
    add_audit(
        db,
        order=order,
        event_type="MANUAL_ORDER_CREATED" if source == OrderSource.MANUAL else "ORDER_SUBMITTED",
        actor_id=actor_id,
        after={
            "source": source,
            "service_mode": service_mode,
            "table_id": order.table_id,
            "line_count": len(order.lines),
            "total_amount": order.total_amount,
        },
    )
    stage_order_changed(db, order, change="submitted")
    return order, raw_token


def create_public_order(
    db: Session,
    *,
    qr_token: str,
    customer: CustomerIn,
    service_mode: ServiceMode,
    lines: list[OrderLineSelectionIn],
) -> tuple[Order, str]:
    try:
        _, table, location = resolve_table_qr(db, qr_token)
    except InvalidTableQr as error:
        raise OrderDomainError(str(error), status_code=410 if error.expired else 404) from error
    # Scanning a table identifies the order's seating context even when the diner
    # switches the fulfillment mode to takeaway before acceptance.
    selected_table = table if service_mode == ServiceMode.DINE_IN else None
    return create_order(
        db,
        location=location,
        table=selected_table,
        customer_payload=customer,
        service_mode=service_mode,
        requested_lines=lines,
        source=OrderSource.QR,
    )


def eligible_waiter(
    db: Session,
    *,
    current: CurrentStaff,
    location_id: str,
    waiter_id: str | None,
) -> StaffAccount:
    assert_location_access(current, location_id)
    target_id = waiter_id
    if target_id is None and StaffRole.WAITER in current.roles:
        target_id = current.staff_id
    if target_id is None:
        raise OrderDomainError("A manager must select an assigned waiter.", status_code=422)
    if StaffRole.MANAGER not in current.roles and target_id != current.staff_id:
        raise OrderDomainError(
            "A waiter cannot assign an order to another staff account.", status_code=403
        )
    waiter = db.scalar(
        select(StaffAccount)
        .join(
            StaffLocationAssignment,
            StaffLocationAssignment.staff_id == StaffAccount.id,
        )
        .join(StaffRoleAssignment, StaffRoleAssignment.staff_id == StaffAccount.id)
        .where(
            StaffAccount.id == target_id,
            StaffAccount.tenant_id == current.tenant_id,
            StaffAccount.is_active.is_(True),
            StaffLocationAssignment.tenant_id == current.tenant_id,
            StaffLocationAssignment.location_id == location_id,
            StaffRoleAssignment.tenant_id == current.tenant_id,
            StaffRoleAssignment.role == StaffRole.WAITER,
        )
    )
    if waiter is None:
        raise OrderDomainError("Eligible waiter not found.", status_code=404)
    return waiter


def _active_visit(db: Session, order: Order, table: DiningTable) -> TableVisit:
    visit = db.scalar(
        select(TableVisit).where(
            TableVisit.tenant_id == order.tenant_id,
            TableVisit.location_id == order.location_id,
            TableVisit.table_id == table.id,
            TableVisit.closed_at.is_(None),
        )
    )
    if visit is None:
        visit = TableVisit(
            tenant_id=order.tenant_id,
            location_id=order.location_id,
            table_id=table.id,
            opened_by_order_id=order.id,
        )
        db.add(visit)
        db.flush()
    table.is_active = True
    return visit


def accept_order(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    waiter_id: str | None,
    chef_id: str | None,
    bartender_id: str | None,
    estimated_wait_minutes: int,
    expected_version: str,
) -> None:
    assert_expected_version(order, expected_version)
    if order.status != OrderStatus.SUBMITTED:
        raise OrderDomainError("Only submitted orders can be accepted.")
    assert_order_operator(
        current,
        location_id=order.location_id,
        owner_id=order.owner_id,
        allow_unowned_waiter=True,
    )
    waiter = eligible_waiter(
        db,
        current=current,
        location_id=order.location_id,
        waiter_id=waiter_id,
    )
    now = datetime.now(UTC)
    before = {"status": order.status, "owner_id": order.owner_id}
    order.owner_id = waiter.id
    order.estimated_wait_minutes = estimated_wait_minutes
    order.status = OrderStatus.PREPARING
    order.accepted_at = now
    assignments: dict[QueueDestination, str | None] = {
        QueueDestination.KITCHEN: chef_id,
        QueueDestination.BAR: bartender_id,
    }
    required_roles = {
        QueueDestination.KITCHEN: StaffRole.CHEF,
        QueueDestination.BAR: StaffRole.BARTENDER,
    }
    for destination, staff_id in assignments.items():
        if not staff_id:
            continue
        eligible = db.scalar(
            select(StaffAccount)
            .join(StaffLocationAssignment, StaffLocationAssignment.staff_id == StaffAccount.id)
            .join(StaffRoleAssignment, StaffRoleAssignment.staff_id == StaffAccount.id)
            .where(
                StaffAccount.id == staff_id,
                StaffAccount.tenant_id == order.tenant_id,
                StaffAccount.is_active.is_(True),
                StaffLocationAssignment.tenant_id == order.tenant_id,
                StaffLocationAssignment.location_id == order.location_id,
                StaffRoleAssignment.tenant_id == order.tenant_id,
                StaffRoleAssignment.role == required_roles[destination],
            )
        )
        if eligible is None:
            raise OrderDomainError(f"Selected {required_roles[destination].value.lower()} is not available at this location.", status_code=422)
        for line in order.lines:
            if line.queue_destination == destination and line.status == LineStatus.PENDING:
                line.status = LineStatus.CLAIMED
                line.claimed_by_id = staff_id
                line.claimed_at = now
    touch(order, now=now)
    if order.table_id:
        table = db.scalar(
            select(DiningTable).where(
                DiningTable.id == order.table_id,
                DiningTable.tenant_id == order.tenant_id,
                DiningTable.location_id == order.location_id,
            )
        )
        if table is None or not table.is_enabled:
            raise OrderDomainError("The selected table is unavailable.")
        order.visit_id = _active_visit(db, order, table).id
        stage_table_changed(db, table, change="visit_opened")
    add_audit(
        db,
        order=order,
        event_type="ORDER_ACCEPTED",
        actor_id=current.staff_id,
        before=before,
        after={
            "status": order.status,
            "owner_id": waiter.id,
            "estimated_wait_minutes": estimated_wait_minutes,
            "chef_id": chef_id,
            "bartender_id": bartender_id,
        },
    )
    stage_order_changed(db, order, change="accepted")


def create_manual_order(
    db: Session,
    *,
    current: CurrentStaff,
    location_id: str,
    table_id: str | None,
    service_mode: ServiceMode,
    customer: CustomerIn,
    lines: list[OrderLineSelectionIn],
    waiter_id: str | None,
    estimated_wait_minutes: int,
) -> tuple[Order, str]:
    assert_location_access(current, location_id)
    location = db.scalar(
        select(Location)
        .options(selectinload(Location.operating_hours))
        .where(Location.id == location_id, Location.tenant_id == current.tenant_id)
    )
    if location is None:
        raise OrderDomainError("Restaurant location not found.", status_code=404)
    table = None
    if table_id:
        table = db.scalar(
            select(DiningTable).where(
                DiningTable.id == table_id,
                DiningTable.tenant_id == current.tenant_id,
                DiningTable.location_id == location_id,
                DiningTable.is_enabled.is_(True),
            )
        )
        if table is None:
            raise OrderDomainError("Table not found.", status_code=404)
    waiter = eligible_waiter(
        db,
        current=current,
        location_id=location_id,
        waiter_id=waiter_id,
    )
    order, token = create_order(
        db,
        location=location,
        table=table,
        customer_payload=customer,
        service_mode=service_mode,
        requested_lines=lines,
        source=OrderSource.MANUAL,
        actor_id=current.staff_id,
        owner_id=waiter.id,
        estimated_wait_minutes=estimated_wait_minutes,
    )
    # Manual creation is the authenticated staff acceptance action.
    now = datetime.now(UTC)
    order.status = OrderStatus.PREPARING
    order.accepted_at = now
    touch(order, now=now)
    if table:
        order.visit_id = _active_visit(db, order, table).id
        stage_table_changed(db, table, change="visit_opened")
    add_audit(
        db,
        order=order,
        event_type="ORDER_ACCEPTED",
        actor_id=current.staff_id,
        after={
            "owner_id": waiter.id,
            "estimated_wait_minutes": estimated_wait_minutes,
            "source": OrderSource.MANUAL,
        },
    )
    stage_order_changed(db, order, change="accepted")
    return order, token


def switch_public_service_mode(
    db: Session,
    *,
    order: Order,
    service_mode: ServiceMode,
    expected_version: str,
) -> None:
    assert_expected_version(order, expected_version)
    if order.status != OrderStatus.SUBMITTED:
        raise OrderDomainError(
            "After acceptance, ask a waiter for help changing this order."
        )
    if order.service_mode == service_mode:
        return
    before = {"service_mode": order.service_mode, "table_id": order.table_id}
    if service_mode == ServiceMode.TAKEAWAY:
        order.table_id = None
    else:
        raise OrderDomainError(
            "This takeaway order is no longer linked to a table. Ask a waiter for help."
        )
    order.service_mode = service_mode
    touch(order)
    add_audit(
        db,
        order=order,
        event_type="ORDER_SERVICE_MODE_CHANGED",
        actor_id=None,
        reason="Changed by diner before acceptance",
        before=before,
        after={"service_mode": order.service_mode, "table_id": order.table_id},
    )
    stage_order_changed(db, order, change="service_mode_changed")


def _close_visit_if_terminal(db: Session, order: Order) -> None:
    if not order.visit_id:
        return
    visit = db.get(TableVisit, order.visit_id)
    if visit is None or visit.closed_at is not None:
        return
    has_active = db.scalar(
        select(
            exists().where(
                Order.visit_id == visit.id,
                Order.id != order.id,
                Order.status.not_in((OrderStatus.PAID, OrderStatus.CANCELLED)),
            )
        )
    )
    if not has_active and order.status in (OrderStatus.PAID, OrderStatus.CANCELLED):
        visit.closed_at = datetime.now(UTC)


def _cancel_all_active_lines(order: Order, *, now: datetime) -> None:
    for line in order.lines:
        if line.status != LineStatus.CANCELLED:
            line.status = LineStatus.CANCELLED
            line.cancelled_at = now
            line.updated_at = now


def cancel_public_order(
    db: Session,
    *,
    order: Order,
    reason: str,
    expected_version: str,
) -> None:
    assert_expected_version(order, expected_version)
    if order.status != OrderStatus.SUBMITTED:
        raise OrderDomainError(
            "After acceptance, ask a waiter for help cancelling this order."
        )
    now = datetime.now(UTC)
    _cancel_all_active_lines(order, now=now)
    order.status = OrderStatus.CANCELLED
    order.cancellation_reason = reason.strip()
    order.cancelled_at = now
    touch(order, now=now)
    recalculate_order(order)
    if order.table_id:
        table = db.get(DiningTable, order.table_id)
        if table:
            synchronize_table_activity(db, table)
            stage_table_changed(db, table, change="order_cancelled")
    add_audit(
        db,
        order=order,
        event_type="ORDER_CANCELLED_BY_DINER",
        actor_id=None,
        reason=reason,
        before={"status": OrderStatus.SUBMITTED},
        after={"status": order.status},
    )
    stage_order_changed(db, order, change="cancelled")


def reassign_order(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    waiter_id: str,
    reason: str,
    expected_version: str,
) -> None:
    assert_expected_version(order, expected_version)
    if StaffRole.MANAGER not in current.roles:
        raise OrderDomainError("Only a manager can reassign an order.", status_code=403)
    if order.status not in (OrderStatus.PREPARING, OrderStatus.READY):
        raise OrderDomainError("Only an accepted active order can be reassigned.")
    target = eligible_waiter(
        db,
        current=current,
        location_id=order.location_id,
        waiter_id=waiter_id,
    )
    old_owner = order.owner_id
    if old_owner == target.id:
        raise OrderDomainError("This waiter already owns the order.")
    order.owner_id = target.id
    touch(order)
    add_audit(
        db,
        order=order,
        event_type="ORDER_REASSIGNED",
        actor_id=current.staff_id,
        reason=reason,
        before={"owner_id": old_owner},
        after={"owner_id": target.id},
    )
    stage_order_changed(db, order, change="reassigned")


def transfer_order(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    table_id: str,
    reason: str,
    expected_version: str,
) -> tuple[DiningTable | None, DiningTable]:
    assert_expected_version(order, expected_version)
    assert_order_operator(current, location_id=order.location_id, owner_id=order.owner_id)
    if order.status not in (OrderStatus.PREPARING, OrderStatus.READY):
        raise OrderDomainError("Only an accepted active order can be transferred.")
    if order.service_mode != ServiceMode.DINE_IN:
        raise OrderDomainError("Only dine-in orders can be transferred to another table.")
    target = db.scalar(
        select(DiningTable).where(
            DiningTable.id == table_id,
            DiningTable.tenant_id == order.tenant_id,
            DiningTable.location_id == order.location_id,
            DiningTable.is_enabled.is_(True),
        )
    )
    if target is None:
        raise OrderDomainError("Target table not found.", status_code=404)
    if target.id == order.table_id:
        raise OrderDomainError("The order is already assigned to this table.")
    source = db.get(DiningTable, order.table_id) if order.table_id else None
    old_visit_id = order.visit_id
    before = {"table_id": order.table_id, "visit_id": old_visit_id}
    order.table_id = target.id
    order.visit_id = _active_visit(db, order, target).id
    order.transfer_notice = (
        f"Your order was moved from {source.label if source else 'its previous table'} "
        f"to {target.label}."
    )
    touch(order)
    db.flush()
    if old_visit_id:
        old_visit = db.get(TableVisit, old_visit_id)
        remaining = db.scalar(
            select(exists().where(Order.visit_id == old_visit_id, Order.id != order.id))
        )
        if old_visit and not remaining:
            old_visit.closed_at = datetime.now(UTC)
    if source:
        synchronize_table_activity(db, source)
        stage_table_changed(db, source, change="order_transferred_from")
    synchronize_table_activity(db, target)
    stage_table_changed(db, target, change="order_transferred_to")
    add_audit(
        db,
        order=order,
        event_type="ORDER_TRANSFERRED",
        actor_id=current.staff_id,
        reason=reason,
        before=before,
        after={
            "table_id": target.id,
            "visit_id": order.visit_id,
            "notice": order.transfer_notice,
        },
    )
    stage_order_changed(db, order, change="transferred")
    return source, target


def _line_before(line: OrderLine) -> dict[str, Any]:
    return {
        "quantity": line.quantity,
        "base_unit_price": line.unit_price,
        "selected_modifiers": line.selected_modifiers,
        "special_instruction": line.special_instruction,
        "status": line.status,
        "subtotal_amount": line.subtotal_amount,
        "vat_amount": line.vat_amount,
        "service_charge_amount": line.service_charge_amount,
        "total_amount": line.total_amount,
    }


def amend_line(
    db: Session,
    *,
    order: Order,
    line_id: str,
    current: CurrentStaff,
    quantity: int | None,
    modifier_option_ids: list[str] | None,
    special_instruction_supplied: bool,
    special_instruction: str | None,
    cancel_line: bool,
    reason: str,
    expected_version: str,
) -> OrderLine:
    assert_expected_version(order, expected_version)
    assert_order_operator(current, location_id=order.location_id, owner_id=order.owner_id)
    if order.status not in (OrderStatus.PREPARING, OrderStatus.READY):
        raise OrderDomainError("Only an accepted active order can be amended.")
    line = next((item for item in order.lines if item.id == line_id), None)
    if line is None:
        raise OrderDomainError("Order line not found.", status_code=404)
    if line.status == LineStatus.CANCELLED:
        raise OrderDomainError("A cancelled line cannot be changed.")
    if line.status in (LineStatus.CLAIMED, LineStatus.READY):
        if not (cancel_line and StaffRole.MANAGER in current.roles):
            raise OrderDomainError(
                "This preparation line is locked. Ask a manager and the preparation station for help."
            )
    now = datetime.now(UTC)
    before = _line_before(line)
    if cancel_line:
        line.status = LineStatus.CANCELLED
        line.cancelled_at = now
    else:
        location = db.get(Location, order.location_id)
        assert location is not None
        requested = OrderLineSelectionIn(
            menu_item_id=line.menu_item_id,
            quantity=quantity if quantity is not None else line.quantity,
            modifier_option_ids=modifier_option_ids
            if modifier_option_ids is not None
            else [item["id"] for item in line.selected_modifiers],
            special_instruction=special_instruction
            if special_instruction_supplied
            else line.special_instruction,
        )
        replacement = _snapshot_line(
            db, order=order, requested=requested, location=location
        )
        line.quantity = replacement.quantity
        line.item_name_snapshot = replacement.item_name_snapshot
        line.modifiers_snapshot = replacement.modifiers_snapshot
        line.selected_modifiers = replacement.selected_modifiers
        line.special_instruction = replacement.special_instruction
        line.queue_destination = replacement.queue_destination
        line.unit_price = replacement.unit_price
        line.subtotal_amount = replacement.subtotal_amount
        line.vat_amount = replacement.vat_amount
        line.service_charge_amount = replacement.service_charge_amount
        line.total_amount = replacement.total_amount
    line.updated_at = now
    recalculate_order(order)
    active = [item for item in order.lines if item.status != LineStatus.CANCELLED]
    if not active:
        order.status = OrderStatus.CANCELLED
        order.cancellation_reason = reason.strip()
        order.cancelled_at = now
        _close_visit_if_terminal(db, order)
    elif all(item.status == LineStatus.READY for item in active):
        order.status = OrderStatus.READY
        order.ready_at = now
    else:
        order.status = OrderStatus.PREPARING
        order.ready_at = None
    touch(order, now=now)
    add_audit(
        db,
        order=order,
        event_type="ORDER_LINE_CANCELLED" if cancel_line else "ORDER_LINE_AMENDED",
        actor_id=current.staff_id,
        reason=reason,
        subject_type="ORDER_LINE",
        subject_id=line.id,
        before=before,
        after=_line_before(line),
    )
    stage_line_changed(db, order, line, change="cancelled" if cancel_line else "amended")
    return line


def cancel_staff_order(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    reason: str,
    expected_version: str,
) -> None:
    assert_expected_version(order, expected_version)
    assert_order_operator(current, location_id=order.location_id, owner_id=order.owner_id)
    if order.status in (OrderStatus.PAID, OrderStatus.CANCELLED):
        raise OrderDomainError("This order can no longer be cancelled.")
    now = datetime.now(UTC)
    before = {"status": order.status}
    _cancel_all_active_lines(order, now=now)
    order.status = OrderStatus.CANCELLED
    order.cancellation_reason = reason.strip()
    order.cancelled_at = now
    touch(order, now=now)
    recalculate_order(order)
    _close_visit_if_terminal(db, order)
    if order.table_id:
        table = db.get(DiningTable, order.table_id)
        if table:
            synchronize_table_activity(db, table)
            stage_table_changed(db, table, change="order_cancelled")
    add_audit(
        db,
        order=order,
        event_type="ORDER_CANCELLED",
        actor_id=current.staff_id,
        reason=reason,
        before=before,
        after={"status": order.status},
    )
    stage_order_changed(db, order, change="cancelled")


def set_wait_time(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    minutes: int,
    source: str,
    expected_version: str,
    request_id: str | None = None,
) -> None:
    assert_expected_version(order, expected_version)
    assert_order_operator(current, location_id=order.location_id, owner_id=order.owner_id)
    if order.status not in (OrderStatus.PREPARING, OrderStatus.DELAYED, OrderStatus.READY):
        raise OrderDomainError("Wait time can be changed only for an accepted active order.")
    before = {"estimated_wait_minutes": order.estimated_wait_minutes}
    order.estimated_wait_minutes = minutes
    touch(order)
    add_audit(
        db,
        order=order,
        event_type="ORDER_WAIT_TIME_CHANGED",
        actor_id=current.staff_id,
        reason=f"{source.lower()} wait time",
        before=before,
        after={"estimated_wait_minutes": minutes, "source": source},
        request_id=request_id,
    )
    stage_order_changed(db, order, change="wait_time_changed")


def delay_order(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    reason: str,
    estimated_wait_minutes: int | None,
    expected_version: str,
) -> None:
    assert_expected_version(order, expected_version)
    assert_order_operator(current, location_id=order.location_id, owner_id=order.owner_id)
    if order.status not in (OrderStatus.PREPARING, OrderStatus.DELAYED):
        raise OrderDomainError("Only a preparing order can be marked delayed.")
    now = datetime.now(UTC)
    before = {"status": order.status, "estimated_wait_minutes": order.estimated_wait_minutes}
    order.status = OrderStatus.DELAYED
    order.delay_reason = reason.strip()
    order.delayed_at = now
    if estimated_wait_minutes is not None:
        order.estimated_wait_minutes = estimated_wait_minutes
    touch(order, now=now)
    add_audit(db, order=order, event_type="ORDER_DELAYED", actor_id=current.staff_id, reason=reason, before=before, after={"status": order.status, "estimated_wait_minutes": order.estimated_wait_minutes})
    stage_order_changed(db, order, change="delayed")


def claim_line(
    db: Session,
    *,
    order: Order,
    line: OrderLine,
    current: CurrentStaff,
    expected_version: str,
) -> None:
    assert_expected_version(order, expected_version)
    assert_station_access(
        current, location_id=line.location_id, destination=line.queue_destination
    )
    if order.status not in (OrderStatus.PREPARING, OrderStatus.DELAYED):
        raise OrderDomainError("Only lines on preparing orders can be claimed.")
    now = datetime.now(UTC)
    result = db.execute(
        update(OrderLine)
        .where(OrderLine.id == line.id, OrderLine.status == LineStatus.PENDING)
        .values(
            status=LineStatus.CLAIMED,
            claimed_by_id=current.staff_id,
            claimed_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise OrderDomainError("This line was already claimed or changed.", status_code=409)
    db.flush()
    db.refresh(line)
    touch(order, now=now)
    add_audit(
        db,
        order=order,
        event_type="PREPARATION_LINE_CLAIMED",
        actor_id=current.staff_id,
        subject_type="ORDER_LINE",
        subject_id=line.id,
        before={"status": LineStatus.PENDING},
        after={"status": line.status, "claimed_by_id": current.staff_id},
    )
    stage_line_changed(db, order, line, change="claimed")


def ready_line(
    db: Session,
    *,
    order: Order,
    line: OrderLine,
    current: CurrentStaff,
    expected_version: str,
    request_id: str | None = None,
) -> None:
    assert_expected_version(order, expected_version)
    assert_station_access(
        current, location_id=line.location_id, destination=line.queue_destination
    )
    if line.claimed_by_id != current.staff_id:
        raise OrderDomainError(
            "Only the preparer who claimed this line can mark it ready.", status_code=403
        )
    now = datetime.now(UTC)
    result = db.execute(
        update(OrderLine)
        .where(
            OrderLine.id == line.id,
            OrderLine.status == LineStatus.CLAIMED,
            OrderLine.claimed_by_id == current.staff_id,
        )
        .values(status=LineStatus.READY, ready_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise OrderDomainError("This line was already completed or changed.", status_code=409)
    db.flush()
    db.refresh(line)
    pending = db.scalar(
        select(
            exists().where(
                OrderLine.order_id == order.id,
                OrderLine.status.not_in((LineStatus.READY, LineStatus.CANCELLED)),
            )
        )
    )
    if not pending:
        order.status = OrderStatus.READY
        order.ready_at = now
    touch(order, now=now)
    add_audit(
        db,
        order=order,
        event_type="PREPARATION_LINE_READY",
        actor_id=current.staff_id,
        subject_type="ORDER_LINE",
        subject_id=line.id,
        before={"status": LineStatus.CLAIMED},
        after={"status": line.status, "order_status": order.status},
        request_id=request_id,
    )
    stage_line_changed(db, order, line, change="ready")


def serve_order(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    expected_version: str,
) -> None:
    assert_expected_version(order, expected_version)
    assert_order_operator(current, location_id=order.location_id, owner_id=order.owner_id)
    if order.status != OrderStatus.READY:
        raise OrderDomainError("Only an order ready for service can be marked served.")
    now = datetime.now(UTC)
    order.status = OrderStatus.SERVED
    order.served_at = now
    touch(order, now=now)
    add_audit(
        db,
        order=order,
        event_type="ORDER_SERVED",
        actor_id=current.staff_id,
        before={"status": OrderStatus.READY},
        after={"status": order.status},
    )
    stage_order_changed(db, order, change="served")


def line_for_prep(
    db: Session, line_id: str, current: CurrentStaff
) -> tuple[OrderLine, Order]:
    if current.tenant_id is None:
        raise OrderDomainError("Preparation line not found.", status_code=404)
    line = db.scalar(
        select(OrderLine).where(
            OrderLine.id == line_id,
            OrderLine.tenant_id == current.tenant_id,
            OrderLine.location_id.in_(current.location_ids),
        )
    )
    if line is None:
        raise OrderDomainError("Preparation line not found.", status_code=404)
    order = scoped_order(db, line.order_id, current)
    return line, order


def modifier_payload(line: OrderLine) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "price_delta": Decimal(str(item["price_delta"])),
        }
        for item in (line.selected_modifiers or [])
    ]


def recommended_wait_minutes(db: Session, location_id: str) -> int:
    active_orders = int(
        db.scalar(
            select(func.count(Order.id)).where(
                Order.location_id == location_id,
                Order.status.in_((OrderStatus.PREPARING, OrderStatus.DELAYED, OrderStatus.READY)),
            )
        )
        or 0
    )
    if active_orders == 0:
        return 5
    if active_orders == 1:
        return 10
    if active_orders <= 3:
        return 15
    if active_orders <= 7:
        return 30
    return 45


def line_payload(line: OrderLine, *, staff: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": line.id,
        "menu_item_id": line.menu_item_id,
        "item_name": line.item_name_snapshot,
        "quantity": line.quantity,
        "base_unit_price": line.unit_price,
        "modifiers": modifier_payload(line),
        "special_instruction": line.special_instruction,
        "subtotal_amount": line.subtotal_amount,
        "vat_amount": line.vat_amount,
        "service_charge_amount": line.service_charge_amount,
        "total_amount": line.total_amount,
    }
    if staff:
        payload.update(
            {
                "queue_destination": line.queue_destination,
                "status": line.status,
                "claimed_at": line.claimed_at,
                "ready_at": line.ready_at,
                "cancelled_at": line.cancelled_at,
            }
        )
    return payload


def public_order_payload(db: Session, order: Order) -> dict[str, Any]:
    table = db.get(DiningTable, order.table_id) if order.table_id else None
    return {
        "id": order.id,
        "status": order.status,
        "diner_status": order.status,
        "service_mode": order.service_mode,
        "table_id": order.table_id,
        "table_label": table.label if table else None,
        "transfer_notice": order.transfer_notice,
        "estimated_wait_minutes": order.estimated_wait_minutes,
        "delay_reason": order.delay_reason,
        "delayed_at": order.delayed_at,
        "recommended_wait_minutes": recommended_wait_minutes(db, order.location_id),
        "wait_time_suggestions": list(WAIT_TIME_SUGGESTIONS),
        "currency": order.currency,
        "subtotal_amount": order.subtotal_amount,
        "vat_amount": order.vat_amount,
        "service_charge_amount": order.service_charge_amount,
        "total_amount": order.total_amount,
        "lines": [
            line_payload(line, staff=False)
            for line in order.lines
            if line.status != LineStatus.CANCELLED
        ],
        "version": order_version(order),
        "created_at": order.created_at,
        "accepted_at": order.accepted_at,
        "ready_at": order.ready_at,
        "served_at": order.served_at,
        "cancelled_at": order.cancelled_at,
        # The persisted cancellation reason is the customer-safe explanation
        # for an order cancellation.  Actor identity and the full audit trail
        # remain available only to the authorised staff timeline endpoint.
        "cancellation_reason": order.cancellation_reason,
    }


def staff_order_payload(
    db: Session, order: Order, current: CurrentStaff
) -> dict[str, Any]:
    payload = public_order_payload(db, order)
    customer = db.get(Customer, order.customer_id)
    owner = db.get(StaffAccount, order.owner_id) if order.owner_id else None
    can_contact = StaffRole.MANAGER in current.roles or (
        StaffRole.WAITER in current.roles and order.owner_id == current.staff_id
    )
    payload.update(
        {
            "tenant_id": order.tenant_id,
            "location_id": order.location_id,
            "source": order.source,
            "owner_id": order.owner_id,
            "owner_name": owner.name if owner else None,
            "customer": {
                "name": customer.name,
                "phone": customer.phone,
                "email": customer.email,
            }
            if customer is not None and can_contact
            else None,
            "lines": [line_payload(line, staff=True) for line in order.lines],
        }
    )
    return payload


def audit_payload(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "subject_type": event.subject_type,
        "subject_id": event.subject_id,
        "actor_id": event.actor_id,
        "reason": event.detail,
        "before_data": event.before_data,
        "after_data": event.after_data,
        "request_id": event.request_id,
        "created_at": event.created_at,
    }
