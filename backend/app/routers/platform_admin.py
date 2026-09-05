"""Platform-only tenant provisioning with a single initial location."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth import CurrentStaff, normalized_email
from app.core.config import get_settings
from app.core.security import issue_invitation_token
from app.db import get_db
from app.dependencies import require_platform_admin
from app.location_service import location_is_currently_open
from app.models import (
    InvitationStatus,
    Location,
    OperatingHour,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    Tenant,
)
from app.platform_admin_schemas import (
    BootstrapOwnerInviteOut,
    TenantBootstrapIn,
    TenantBootstrapOut,
)


router = APIRouter(prefix="/api/v1/platform", tags=["platform administration"])


def _location_out(location: Location) -> dict:
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


def _load_location(db: Session, location_id: str) -> Location:
    location = db.scalar(
        select(Location)
        .options(selectinload(Location.operating_hours))
        .where(Location.id == location_id)
    )
    assert location is not None
    return location


@router.post("/tenants/bootstrap", response_model=TenantBootstrapOut, status_code=status.HTTP_201_CREATED)
def bootstrap_tenant(
    payload: TenantBootstrapIn,
    db: Session = Depends(get_db),
    _: CurrentStaff = Depends(require_platform_admin),
) -> dict:
    """Create a tenant boundary, its first location, optional hours and owner invite.

    The invitation token is intentionally returned once for the platform's delivery
    flow; only its SHA-256 hash is persisted, and acceptance uses the existing
    ``/api/v1/staff/auth/invitations/accept`` endpoint.
    """

    tenant = Tenant(name=payload.tenant_name)
    location = Location(tenant=tenant, **payload.initial_location.model_dump())
    db.add_all([tenant, location])
    owner_out: BootstrapOwnerInviteOut | None = None
    try:
        db.flush()
        db.add_all(
            OperatingHour(
                tenant_id=tenant.id,
                location_id=location.id,
                **hours.model_dump(),
            )
            for hours in payload.operating_hours
        )
        if payload.owner_invitation:
            email = normalized_email(str(payload.owner_invitation.email))
            if db.scalar(select(StaffAccount.id).where(StaffAccount.email == email)):
                raise HTTPException(status_code=409, detail="A staff account already exists for this email.")
            raw_token, token_hash = issue_invitation_token()
            expires_at = datetime.now(UTC) + timedelta(hours=get_settings().invitation_ttl_hours)
            owner = StaffAccount(
                tenant_id=tenant.id,
                name=payload.owner_invitation.name,
                email=email,
                invitation_status=InvitationStatus.PENDING,
                invitation_token_hash=token_hash,
                invitation_expires_at=expires_at,
                is_active=True,
            )
            db.add(owner)
            db.flush()
            db.add_all(
                [
                    StaffRoleAssignment(
                        tenant_id=tenant.id,
                        staff_id=owner.id,
                        role=StaffRole.TENANT_OWNER,
                    ),
                    StaffLocationAssignment(
                        tenant_id=tenant.id,
                        location_id=location.id,
                        staff_id=owner.id,
                    ),
                ]
            )
            owner_out = BootstrapOwnerInviteOut(
                staff_id=owner.id,
                email=email,
                expires_at=expires_at,
                acceptance_token=raw_token,
            )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="The tenant, location, or owner invitation conflicts with existing data.") from None

    location = _load_location(db, location.id)
    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "initial_location": _location_out(location),
        "owner_invitation": owner_out,
    }
