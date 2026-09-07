"""Authenticated waiter and manager order operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentStaff
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import assert_location_access, require_roles
from app.events import EventBus, commit_and_publish
from app.models import AuditEvent, Order, StaffAccount, StaffLocationAssignment, StaffRole, StaffRoleAssignment
from app.order_schemas import (
    AcceptOrderIn,
    AmendOrderLineIn,
    AuditEventOut,
    DelayOrderIn,
    ManualOrderCreateIn,
    PreparerOut,
    ReassignOrderIn,
    ReasonedMutationIn,
    SetWaitTimeIn,
    StaffOrderCreatedOut,
    StaffOrderOut,
    TransferOrderIn,
    VersionedMutationIn,
)
from app.order_service import (
    OrderDomainError,
    accept_order,
    amend_line,
    audit_payload,
    cancel_staff_order,
    create_manual_order,
    delay_order,
    issue_order_realtime_token,
    raise_order_http,
    reassign_order,
    scoped_order,
    serve_order,
    set_wait_time,
    staff_order_payload,
    transfer_order,
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


def _existing_idempotent_audit(
    db: Session, *, order: Order, request_id: str | None, event_type: str
) -> bool:
    if not request_id:
        return False
    if len(request_id) > 100:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long.")
    return bool(
        db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.tenant_id == order.tenant_id,
                AuditEvent.location_id == order.location_id,
                AuditEvent.subject_id == order.id,
                AuditEvent.event_type == event_type,
                AuditEvent.request_id == request_id,
            )
        )
    )


def create_staff_orders_router(event_bus: EventBus | None = None) -> APIRouter:
    settings = get_settings()
    bus = event_bus or RedisEventBus(
        settings.redis_url, history_limit=settings.event_history_limit
    )
    router = APIRouter(prefix="/api/v1/staff", tags=["staff orders"])
    order_staff = require_roles(StaffRole.WAITER, StaffRole.MANAGER)

    @router.get("/orders", response_model=list[StaffOrderOut])
    def list_orders(
        location_id: str | None = Query(default=None),
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> list[dict]:
        location = _active_location(current, location_id)
        rows = db.scalars(
            select(Order)
            .where(
                Order.tenant_id == current.tenant_id,
                Order.location_id == location,
            )
            .order_by(Order.created_at.desc(), Order.id)
        )
        return [staff_order_payload(db, row, current) for row in rows]

    @router.get("/preparers", response_model=list[PreparerOut])
    def list_preparers(
        location_id: str | None = Query(default=None),
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> list[dict]:
        location = _active_location(current, location_id)
        rows = db.scalars(
            select(StaffAccount)
            .join(StaffLocationAssignment, StaffLocationAssignment.staff_id == StaffAccount.id)
            .where(StaffAccount.tenant_id == current.tenant_id, StaffAccount.is_active.is_(True), StaffLocationAssignment.location_id == location)
            .order_by(StaffAccount.name, StaffAccount.id)
        ).unique()
        result = []
        for account in rows:
            roles = list(db.scalars(select(StaffRoleAssignment.role).where(StaffRoleAssignment.tenant_id == current.tenant_id, StaffRoleAssignment.staff_id == account.id)))
            preparer_roles = [role for role in roles if role in (StaffRole.CHEF, StaffRole.BARTENDER)]
            if preparer_roles:
                result.append({"id": account.id, "name": account.name, "roles": preparer_roles})
        return result

    @router.get("/orders/{order_id}", response_model=StaffOrderOut)
    def order_detail(
        order_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            return staff_order_payload(db, scoped_order(db, order_id, current), current)
        except OrderDomainError as error:
            raise_order_http(error)

    @router.post(
        "/orders/manual",
        response_model=StaffOrderCreatedOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def manual_order(
        payload: ManualOrderCreateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            order, raw_token = create_manual_order(
                db,
                current=current,
                location_id=payload.location_id,
                table_id=payload.table_id,
                service_mode=payload.service_mode,
                customer=payload.customer,
                lines=payload.lines,
                waiter_id=payload.waiter_id,
                estimated_wait_minutes=payload.estimated_wait_minutes,
            )
            await commit_and_publish(db, bus)
            return {
                **staff_order_payload(db, order, current),
                "access_token": raw_token,
                "realtime_token": issue_order_realtime_token(order.id),
            }
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/orders/{order_id}/delay", response_model=StaffOrderOut)
    async def delay(
        order_id: str,
        payload: DelayOrderIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            delay_order(db, order=order, current=current, reason=payload.reason, estimated_wait_minutes=payload.estimated_wait_minutes, expected_version=payload.expected_version)
            await commit_and_publish(db, bus)
            return staff_order_payload(db, order, current)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/orders/{order_id}/accept", response_model=StaffOrderOut)
    async def accept(
        order_id: str,
        payload: AcceptOrderIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            accept_order(
                db,
                order=order,
                current=current,
                waiter_id=payload.waiter_id,
                chef_id=payload.chef_id,
                bartender_id=payload.bartender_id,
                estimated_wait_minutes=payload.estimated_wait_minutes,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return staff_order_payload(db, order, current)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/orders/{order_id}/reassign", response_model=StaffOrderOut)
    async def reassign(
        order_id: str,
        payload: ReassignOrderIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.MANAGER)),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            reassign_order(
                db,
                order=order,
                current=current,
                waiter_id=payload.waiter_id,
                reason=payload.reason,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return staff_order_payload(db, order, current)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/orders/{order_id}/transfer", response_model=StaffOrderOut)
    async def transfer(
        order_id: str,
        payload: TransferOrderIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            transfer_order(
                db,
                order=order,
                current=current,
                table_id=payload.table_id,
                reason=payload.reason,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return staff_order_payload(db, order, current)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.patch(
        "/orders/{order_id}/lines/{line_id}", response_model=StaffOrderOut
    )
    async def amend_order_line(
        order_id: str,
        line_id: str,
        payload: AmendOrderLineIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            amend_line(
                db,
                order=order,
                line_id=line_id,
                current=current,
                quantity=payload.quantity,
                modifier_option_ids=payload.modifier_option_ids,
                special_instruction_supplied="special_instruction"
                in payload.model_fields_set,
                special_instruction=payload.special_instruction,
                cancel_line=payload.cancel_line,
                reason=payload.reason,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return staff_order_payload(db, order, current)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/orders/{order_id}/cancel", response_model=StaffOrderOut)
    async def cancel(
        order_id: str,
        payload: ReasonedMutationIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            cancel_staff_order(
                db,
                order=order,
                current=current,
                reason=payload.reason,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return staff_order_payload(db, order, current)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/orders/{order_id}/wait-time", response_model=StaffOrderOut)
    async def update_wait_time(
        order_id: str,
        payload: SetWaitTimeIn,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            if not _existing_idempotent_audit(
                db,
                order=order,
                request_id=idempotency_key,
                event_type="ORDER_WAIT_TIME_CHANGED",
            ):
                set_wait_time(
                    db,
                    order=order,
                    current=current,
                    minutes=payload.minutes,
                    source=payload.source,
                    expected_version=payload.expected_version,
                    request_id=idempotency_key,
                )
                await commit_and_publish(db, bus)
            return staff_order_payload(db, order, current)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/orders/{order_id}/serve", response_model=StaffOrderOut)
    async def serve(
        order_id: str,
        payload: VersionedMutationIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(order_staff),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            serve_order(
                db,
                order=order,
                current=current,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return staff_order_payload(db, order, current)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.get(
        "/orders/{order_id}/timeline", response_model=list[AuditEventOut]
    )
    def order_timeline(
        order_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.MANAGER)),
    ) -> list[dict]:
        try:
            order = scoped_order(db, order_id, current)
        except OrderDomainError as error:
            raise_order_http(error)
        events = db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == order.tenant_id,
                AuditEvent.location_id == order.location_id,
                (
                    (AuditEvent.subject_type == "ORDER")
                    & (AuditEvent.subject_id == order.id)
                    | (
                        (AuditEvent.subject_type == "ORDER_LINE")
                        & AuditEvent.subject_id.in_([line.id for line in order.lines])
                    )
                ),
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
        return [audit_payload(event) for event in events]

    @router.get("/members")
    def staff_members(
        location_id: str | None = Query(default=None),
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)
        ),
    ) -> list[dict]:
        location = _active_location(current, location_id)
        rows = db.execute(
            select(StaffAccount, StaffRoleAssignment.role)
            .join(
                StaffLocationAssignment,
                StaffLocationAssignment.staff_id == StaffAccount.id,
            )
            .join(
                StaffRoleAssignment,
                StaffRoleAssignment.staff_id == StaffAccount.id,
            )
            .where(
                StaffAccount.tenant_id == current.tenant_id,
                StaffAccount.is_active.is_(True),
                StaffLocationAssignment.tenant_id == current.tenant_id,
                StaffLocationAssignment.location_id == location,
                StaffRoleAssignment.tenant_id == current.tenant_id,
            )
            .order_by(StaffAccount.name, StaffRoleAssignment.role)
        )
        grouped: dict[str, dict] = {}
        for account, role in rows:
            member = grouped.setdefault(
                account.id, {"id": account.id, "name": account.name, "roles": []}
            )
            member["roles"].append(role.value)
        return list(grouped.values())

    return router


router = create_staff_orders_router()
