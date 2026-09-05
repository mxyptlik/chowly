"""Tenant-owned location configuration and operating-hours endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth import CurrentStaff
from app.db import get_db
from app.dependencies import assert_location_access, require_roles, scoped_resource_or_404
from app.location_schemas import (
    LocationCreateIn,
    LocationOut,
    LocationUpdateIn,
    OperatingHourIn,
    ReservationPolicyIn,
)
from app.location_service import location_is_currently_open
from app.models import (
    AuditEvent,
    Location,
    OperatingHour,
    StaffLocationAssignment,
    StaffRole,
)


router = APIRouter(prefix="/api/v1/staff/locations", tags=["locations"])

@router.put("/{location_id}/reservation-policy")
def replace_reservation_policy(location_id: str, payload: ReservationPolicyIn, db: Session = Depends(get_db), current: CurrentStaff = Depends(require_roles(StaffRole.MANAGER, StaffRole.TENANT_OWNER))):
    location = scoped_resource_or_404(db, Location, location_id, current)
    location.customer_edits_enabled = payload.customer_edits_enabled
    location.customer_edit_cutoff_minutes = payload.customer_edit_cutoff_minutes
    location.customer_cancellations_enabled = payload.customer_cancellations_enabled
    location.customer_cancellation_cutoff_minutes = payload.customer_cancellation_cutoff_minutes
    db.add(AuditEvent(tenant_id=location.tenant_id, location_id=location.id, actor_id=current.staff_id, event_type="RESERVATION_POLICY_UPDATED", subject_type="LOCATION", subject_id=location.id, detail="Reservation customer policy updated"))
    db.commit()
    return {"customer_edits_enabled": location.customer_edits_enabled, "customer_edit_cutoff_minutes": location.customer_edit_cutoff_minutes, "customer_cancellations_enabled": location.customer_cancellations_enabled, "customer_cancellation_cutoff_minutes": location.customer_cancellation_cutoff_minutes}


def _location_query():
    return select(Location).options(selectinload(Location.operating_hours))


def _out(location: Location) -> dict:
    return {
        "id": location.id,
        "tenant_id": location.tenant_id,
        "name": location.name,
        "slug": location.slug,
        "address": location.address,
        "cover_image_url": location.cover_image_url,
        "currency": location.currency,
        "vat_rate": location.vat_rate,
        "service_charge_rate": location.service_charge_rate,
        "timezone": location.timezone,
        "is_active": location.is_active,
        "is_open": location.is_open,
        "currently_open": location_is_currently_open(location),
        "customer_edits_enabled": location.customer_edits_enabled,
        "customer_edit_cutoff_minutes": location.customer_edit_cutoff_minutes,
        "customer_cancellations_enabled": location.customer_cancellations_enabled,
        "customer_cancellation_cutoff_minutes": location.customer_cancellation_cutoff_minutes,
        "operating_hours": sorted(location.operating_hours, key=lambda row: row.weekday),
    }


def _audit(
    db: Session,
    *,
    current: CurrentStaff,
    location: Location,
    event_type: str,
    subject_type: str,
    subject_id: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=location.tenant_id,
            location_id=location.id,
            actor_id=current.staff_id,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            before_data=before,
            after_data=after,
        )
    )


@router.get("", response_model=list[LocationOut])
def list_locations(
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
) -> list[dict]:
    if current.tenant_id is None:
        return []
    rows = db.scalars(
        _location_query()
        .where(
            Location.tenant_id == current.tenant_id,
            Location.id.in_(current.location_ids),
        )
        .order_by(Location.name, Location.id)
    ).unique()
    return [_out(row) for row in rows]


@router.post("", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
def create_location(
    payload: LocationCreateIn,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> dict:
    if current.tenant_id is None:
        raise HTTPException(status_code=403, detail="Restaurant tenant access is required.")
    location = Location(
        tenant_id=current.tenant_id,
        **payload.model_dump(),
    )
    db.add(location)
    try:
        db.flush()
        db.add(
            StaffLocationAssignment(
                tenant_id=current.tenant_id,
                location_id=location.id,
                staff_id=current.staff_id,
                assigned_by_id=current.staff_id,
            )
        )
        _audit(
            db,
            current=current,
            location=location,
            event_type="LOCATION_CREATED",
            subject_type="LOCATION",
            subject_id=location.id,
            after=payload.model_dump(mode="json"),
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A location with this name already exists.") from None
    location = db.scalar(_location_query().where(Location.id == location.id))
    assert location is not None
    return _out(location)


@router.get("/{location_id}", response_model=LocationOut)
def get_location(
    location_id: str,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
) -> dict:
    assert_location_access(current, location_id)
    location = db.scalar(
        _location_query().where(
            Location.id == location_id,
            Location.tenant_id == current.tenant_id,
        )
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return _out(location)


@router.patch("/{location_id}", response_model=LocationOut)
def update_location(
    location_id: str,
    payload: LocationUpdateIn,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> dict:
    location = scoped_resource_or_404(db, Location, location_id, current)
    before = {
        key: str(getattr(location, key))
        for key in payload.model_dump(exclude_unset=True)
    }
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, key, value)
    _audit(
        db,
        current=current,
        location=location,
        event_type="LOCATION_UPDATED",
        subject_type="LOCATION",
        subject_id=location.id,
        before=before,
        after=payload.model_dump(mode="json", exclude_unset=True),
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="The location update conflicts with existing data.") from None
    location = db.scalar(_location_query().where(Location.id == location.id))
    assert location is not None
    return _out(location)


@router.delete(
    "/{location_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def deactivate_location(
    location_id: str,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> Response:
    location = scoped_resource_or_404(db, Location, location_id, current)
    location.is_active = False
    location.is_open = False
    _audit(
        db,
        current=current,
        location=location,
        event_type="LOCATION_DEACTIVATED",
        subject_type="LOCATION",
        subject_id=location.id,
        before={"is_active": True},
        after={"is_active": False},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{location_id}/operating-hours", response_model=LocationOut)
def replace_operating_hours(
    location_id: str,
    payload: list[OperatingHourIn],
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> dict:
    if len(payload) > 7 or len({row.weekday for row in payload}) != len(payload):
        raise HTTPException(status_code=422, detail="Provide at most one operating-hours row per weekday.")
    location = db.scalar(
        _location_query().where(
            Location.id == location_id,
            Location.tenant_id == current.tenant_id,
        )
    )
    assert_location_access(current, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    before = [
        {
            "weekday": row.weekday,
            "opens_at": str(row.opens_at) if row.opens_at else None,
            "closes_at": str(row.closes_at) if row.closes_at else None,
            "is_closed": row.is_closed,
        }
        for row in location.operating_hours
    ]
    location.operating_hours.clear()
    # PostgreSQL enforces the (tenant, location, weekday) unique key immediately.
    # Flush orphan deletes before adding replacement rows for the same weekdays.
    db.flush()
    location.operating_hours.extend(
        OperatingHour(
            tenant_id=location.tenant_id,
            location_id=location.id,
            **row.model_dump(),
        )
        for row in payload
    )
    _audit(
        db,
        current=current,
        location=location,
        event_type="OPERATING_HOURS_UPDATED",
        subject_type="LOCATION",
        subject_id=location.id,
        before={"hours": before},
        after={"hours": [row.model_dump(mode="json") for row in payload]},
    )
    db.commit()
    location = db.scalar(_location_query().where(Location.id == location.id))
    assert location is not None
    return _out(location)
