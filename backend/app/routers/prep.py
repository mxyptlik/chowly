"""Role-partitioned kitchen and bar preparation queues."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.auth import CurrentStaff
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import assert_location_access, require_roles
from app.events import EventBus, commit_and_publish
from app.models import AuditEvent, DiningTable, LineStatus, Order, OrderLine, OrderStatus, QueueDestination, StaffRole
from app.order_schemas import PrepLineOut, PrepMutationIn
from app.order_service import (
    OrderDomainError,
    claim_line,
    line_for_prep,
    modifier_payload,
    order_version,
    raise_order_http,
    ready_line,
)
from app.realtime import RedisEventBus


def _active_location(current: CurrentStaff, requested: str | None = None) -> str:
    location_id = requested or current.active_location_id
    if not location_id:
        raise HTTPException(
            status_code=403, detail="Select an assigned restaurant location first."
        )
    assert_location_access(current, location_id)
    return location_id


def _destinations(current: CurrentStaff) -> list[QueueDestination]:
    destinations: list[QueueDestination] = []
    if StaffRole.CHEF in current.roles:
        destinations.append(QueueDestination.KITCHEN)
    if StaffRole.BARTENDER in current.roles:
        destinations.append(QueueDestination.BAR)
    return destinations


def _prep_payload(db: Session, line: OrderLine, order: Order) -> dict:
    table = db.get(DiningTable, order.table_id) if order.table_id else None
    return {
        "line_id": line.id,
        "order_id": order.id,
        "table_label": table.label if table else "Takeaway",
        "item_name": line.item_name_snapshot,
        "quantity": line.quantity,
        "modifiers": modifier_payload(line),
        "special_instruction": line.special_instruction,
        "queue_destination": line.queue_destination,
        "status": line.status,
        "claimed_by_id": line.claimed_by_id,
        "claimed_at": line.claimed_at,
        "order_version": order_version(order),
    }


def create_prep_router(event_bus: EventBus | None = None) -> APIRouter:
    settings = get_settings()
    bus = event_bus or RedisEventBus(
        settings.redis_url, history_limit=settings.event_history_limit
    )
    router = APIRouter(prefix="/api/v1/staff", tags=["preparation"])
    prep_roles = require_roles(StaffRole.CHEF, StaffRole.BARTENDER)

    @router.get("/prep", response_model=list[PrepLineOut])
    def preparation_queue(
        location_id: str | None = Query(default=None),
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(prep_roles),
    ) -> list[dict]:
        location = _active_location(current, location_id)
        rows = db.execute(
            select(OrderLine, Order)
            .join(
                Order,
                (Order.id == OrderLine.order_id)
                & (Order.tenant_id == OrderLine.tenant_id)
                & (Order.location_id == OrderLine.location_id),
            )
            .where(
                OrderLine.tenant_id == current.tenant_id,
                OrderLine.location_id == location,
                OrderLine.queue_destination.in_(_destinations(current)),
                OrderLine.status.in_((LineStatus.PENDING, LineStatus.CLAIMED)),
                Order.status.in_((OrderStatus.PREPARING, OrderStatus.DELAYED)),
                or_(
                    OrderLine.status == LineStatus.PENDING,
                    and_(OrderLine.status == LineStatus.CLAIMED, OrderLine.claimed_by_id == current.staff_id),
                ),
            )
            .order_by(Order.created_at, OrderLine.created_at, OrderLine.id)
        )
        return [_prep_payload(db, line, order) for line, order in rows]

    @router.post("/lines/{line_id}/claim", response_model=PrepLineOut)
    async def claim_preparation_line(
        line_id: str,
        payload: PrepMutationIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(prep_roles),
    ) -> dict:
        try:
            line, order = line_for_prep(db, line_id, current)
            claim_line(
                db,
                order=order,
                line=line,
                current=current,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return _prep_payload(db, line, order)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/lines/{line_id}/ready", response_model=PrepLineOut)
    async def mark_preparation_line_ready(
        line_id: str,
        payload: PrepMutationIn,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(prep_roles),
    ) -> dict:
        try:
            line, order = line_for_prep(db, line_id, current)
            if idempotency_key and len(idempotency_key) > 100:
                raise HTTPException(status_code=422, detail="Idempotency-Key is too long.")
            already_applied = bool(
                idempotency_key
                and db.scalar(
                    select(AuditEvent.id).where(
                        AuditEvent.tenant_id == order.tenant_id,
                        AuditEvent.location_id == order.location_id,
                        AuditEvent.subject_type == "ORDER_LINE",
                        AuditEvent.subject_id == line.id,
                        AuditEvent.event_type == "PREPARATION_LINE_READY",
                        AuditEvent.request_id == idempotency_key,
                    )
                )
            )
            if not already_applied:
                ready_line(
                    db,
                    order=order,
                    line=line,
                    current=current,
                    expected_version=payload.expected_version,
                    request_id=idempotency_key,
                )
                await commit_and_publish(db, bus)
            return _prep_payload(db, line, order)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    return router


router = create_prep_router()
