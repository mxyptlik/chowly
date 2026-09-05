"""Public request and assigned-location staff reservation endpoints.

Application composition must mount ``router`` (or a router returned by
``create_reservations_router``). Tests inject an in-memory event bus through the
factory; production defaults to the configured Redis event bus.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.auth import CurrentStaff
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import require_roles
from app.events import EventBus, commit_and_publish
from app.models import Location, ReservationStatus, StaffRole, Tenant, TenantLifecycle
from app.realtime import RedisEventBus
from app.reservation_schemas import (
    ReservationConfirmIn,
    ReservationCreateIn,
    ReservationPublicCreatedOut,
    ReservationPublicOut,
    ReservationPublicUpdateIn,
    ReservationQrPassOut,
    ReservationReasonIn,
    ReservationSeatIn,
    ReservationStaffOut,
)
from app.reservation_service import (
    ReservationDomainError,
    create_reservation,
    list_scoped_reservations,
    public_payload,
    public_created_payload,
    public_reservation_by_access_token,
    scoped_reservation,
    staff_payload,
    transition_reservation,
    update_public_reservation,
    cancel_public_reservation,
    issue_qr_pass,
    reservation_by_qr_pass,
    check_in_reservation,
)


def _raise_domain(error: ReservationDomainError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def create_reservations_router(event_bus: EventBus | None = None) -> APIRouter:
    settings = get_settings()
    bus = event_bus or RedisEventBus(
        settings.redis_url,
        history_limit=settings.event_history_limit,
    )
    reservations_router = APIRouter(tags=["reservations"])
    staff_dependency = require_roles(StaffRole.MANAGER, StaffRole.WAITER)

    @reservations_router.post(
        "/api/v1/public/reservations",
        response_model=ReservationPublicCreatedOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def request_reservation(
        payload: ReservationCreateIn,
        db: Session = Depends(get_db),
    ) -> dict[str, object]:
        if payload.tenant_slug or payload.location_slug:
            if not payload.tenant_slug or not payload.location_slug:
                raise HTTPException(status_code=422, detail="Restaurant and location are required.")
            location = db.scalar(
                select(Location)
                .join(Tenant)
                .where(
                    Tenant.slug == payload.tenant_slug,
                    Tenant.lifecycle == TenantLifecycle.ACTIVE,
                    Location.slug == payload.location_slug,
                    Location.is_active.is_(True),
                )
            )
            if location is None:
                raise HTTPException(status_code=404, detail="Restaurant location not found.")
            payload = payload.model_copy(update={"location_id": location.id})
        if not payload.location_id:
            raise HTTPException(status_code=422, detail="Restaurant and location are required.")
        try:
            reservation, access_token = create_reservation(db, payload)
            await commit_and_publish(db, bus)
            return public_created_payload(reservation, access_token)
        except ReservationDomainError as error:
            db.rollback()
            _raise_domain(error)

    @reservations_router.get(
        "/api/v1/public/reservations/status/{access_token}",
        response_model=ReservationPublicOut,
    )
    def public_reservation_status(
        access_token: str,
        db: Session = Depends(get_db),
    ) -> dict[str, object]:
        """Return a status only for the opaque token issued at creation time."""

        try:
            return public_payload(public_reservation_by_access_token(db, access_token))
        except ReservationDomainError as error:
            _raise_domain(error)

    @reservations_router.patch("/api/v1/public/reservations/status/{access_token}", response_model=ReservationPublicOut)
    async def update_public_reservation_endpoint(access_token: str, payload: ReservationPublicUpdateIn, db: Session = Depends(get_db)) -> dict[str, object]:
        try:
            reservation = update_public_reservation(db, public_reservation_by_access_token(db, access_token), payload)
            await commit_and_publish(db, bus)
            return public_payload(reservation)
        except ReservationDomainError as error:
            db.rollback(); _raise_domain(error)

    @reservations_router.post("/api/v1/public/reservations/status/{access_token}/cancel", response_model=ReservationPublicOut)
    async def cancel_public_reservation_endpoint(access_token: str, db: Session = Depends(get_db)) -> dict[str, object]:
        try:
            reservation = cancel_public_reservation(db, public_reservation_by_access_token(db, access_token))
            await commit_and_publish(db, bus)
            return public_payload(reservation)
        except ReservationDomainError as error:
            db.rollback(); _raise_domain(error)

    @reservations_router.post("/api/v1/public/reservations/status/{access_token}/qr-pass", response_model=ReservationQrPassOut)
    async def create_qr_pass(access_token: str, db: Session = Depends(get_db)) -> dict[str, str]:
        try:
            reservation = public_reservation_by_access_token(db, access_token)
            token = issue_qr_pass(reservation)
            await commit_and_publish(db, bus)
            return {"qr_pass_token": token}
        except ReservationDomainError as error:
            db.rollback(); _raise_domain(error)

    @reservations_router.get("/api/v1/staff/reservations/qr-pass/{qr_pass_token}", response_model=ReservationStaffOut)
    def verify_qr_pass(qr_pass_token: str, db: Session = Depends(get_db), current: CurrentStaff = Depends(staff_dependency)) -> dict[str, object]:
        try:
            return staff_payload(reservation_by_qr_pass(db, qr_pass_token, current))
        except ReservationDomainError as error:
            _raise_domain(error)

    @reservations_router.post("/api/v1/staff/reservations/qr-pass/{qr_pass_token}/check-in", response_model=ReservationStaffOut)
    async def check_in_qr_pass(qr_pass_token: str, db: Session = Depends(get_db), current: CurrentStaff = Depends(staff_dependency)) -> dict[str, object]:
        try:
            reservation = check_in_reservation(db, reservation_by_qr_pass(db, qr_pass_token, current), current)
            await commit_and_publish(db, bus)
            return staff_payload(reservation)
        except ReservationDomainError as error:
            db.rollback(); _raise_domain(error)

    @reservations_router.get(
        "/api/v1/staff/locations/{location_id}/reservations",
        response_model=list[ReservationStaffOut],
    )
    def reservation_queue(
        location_id: str,
        reservation_status: ReservationStatus | None = Query(default=None, alias="status"),
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(staff_dependency),
    ) -> list[dict[str, object]]:
        try:
            reservations = list_scoped_reservations(
                db,
                current,
                location_id=location_id,
                status=reservation_status,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            return [staff_payload(reservation) for reservation in reservations]
        except ReservationDomainError as error:
            _raise_domain(error)

    @reservations_router.get(
        "/api/v1/staff/reservations/{reservation_id}",
        response_model=ReservationStaffOut,
    )
    def reservation_detail(
        reservation_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(staff_dependency),
    ) -> dict[str, object]:
        try:
            return staff_payload(scoped_reservation(db, reservation_id, current))
        except ReservationDomainError as error:
            _raise_domain(error)

    async def apply_transition(
        reservation_id: str,
        target: ReservationStatus,
        current: CurrentStaff,
        db: Session,
        *,
        table_id: str | None = None,
        reason_or_note: str | None = None,
    ) -> dict[str, object]:
        try:
            reservation = scoped_reservation(db, reservation_id, current)
            transition_reservation(
                db,
                reservation,
                current,
                target=target,
                table_id=table_id,
                reason_or_note=reason_or_note,
            )
            await commit_and_publish(db, bus)
            return staff_payload(reservation)
        except ReservationDomainError as error:
            db.rollback()
            _raise_domain(error)

    @reservations_router.post(
        "/api/v1/staff/reservations/{reservation_id}/confirm",
        response_model=ReservationStaffOut,
    )
    async def confirm_reservation(
        reservation_id: str,
        payload: ReservationConfirmIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(staff_dependency),
    ) -> dict[str, object]:
        return await apply_transition(
            reservation_id,
            ReservationStatus.CONFIRMED,
            current,
            db,
            table_id=payload.table_id,
            reason_or_note=payload.note,
        )

    @reservations_router.post(
        "/api/v1/staff/reservations/{reservation_id}/reject",
        response_model=ReservationStaffOut,
    )
    async def reject_reservation(
        reservation_id: str,
        payload: ReservationReasonIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(staff_dependency),
    ) -> dict[str, object]:
        return await apply_transition(
            reservation_id,
            ReservationStatus.REJECTED,
            current,
            db,
            reason_or_note=payload.reason,
        )

    @reservations_router.post(
        "/api/v1/staff/reservations/{reservation_id}/cancel",
        response_model=ReservationStaffOut,
    )
    async def cancel_reservation(
        reservation_id: str,
        payload: ReservationReasonIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(staff_dependency),
    ) -> dict[str, object]:
        return await apply_transition(
            reservation_id,
            ReservationStatus.CANCELLED,
            current,
            db,
            reason_or_note=payload.reason,
        )

    @reservations_router.post(
        "/api/v1/staff/reservations/{reservation_id}/seat",
        response_model=ReservationStaffOut,
    )
    async def seat_reservation(
        reservation_id: str,
        payload: ReservationSeatIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(staff_dependency),
    ) -> dict[str, object]:
        return await apply_transition(
            reservation_id,
            ReservationStatus.SEATED,
            current,
            db,
            table_id=payload.table_id,
            reason_or_note=payload.note,
        )

    return reservations_router


router = create_reservations_router()
