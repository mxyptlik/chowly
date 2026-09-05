"""Public self-service restaurant registration. It creates a private tenant."""
from __future__ import annotations

from datetime import time
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import CurrentStaff, normalized_email
from app.core.security import hash_password
from app.db import get_db
from app.dependencies import require_roles
from app.models import DiningTable, InvitationStatus, Location, MenuCategory, MenuItem, OperatingHour, StaffAccount, StaffLocationAssignment, StaffRole, StaffRoleAssignment, Tenant, TenantLifecycle
from app.onboarding_schemas import RestaurantRegistrationIn, RestaurantRegistrationOut
from app.public_service import unique_location_slug, unique_tenant_slug

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])
_attempts: dict[str, int] = {}


def _rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    count = _attempts.get(client, 0) + 1
    _attempts[client] = count
    if count > 12:
        raise HTTPException(status_code=429, detail="Please try again later.")


def _publish_readiness(db: Session, *, tenant_id: str) -> list[str]:
    """Return human-readable prerequisites missing from a public restaurant.

    Publishing is intentionally checked on the server: hiding the button in the
    onboarding UI must never accidentally expose an incomplete tenant.
    """
    active_location_ids = list(
        db.scalars(
            select(Location.id).where(
                Location.tenant_id == tenant_id,
                Location.is_active.is_(True),
            )
        )
    )
    missing: list[str] = []
    if not active_location_ids:
        return ["Add and activate at least one restaurant location."]

    has_opening_hours = db.scalar(
        select(OperatingHour.id).where(
            OperatingHour.tenant_id == tenant_id,
            OperatingHour.location_id.in_(active_location_ids),
            OperatingHour.is_closed.is_(False),
            OperatingHour.opens_at.is_not(None),
            OperatingHour.closes_at.is_not(None),
        ).limit(1)
    )
    if not has_opening_hours:
        missing.append("Set opening hours for at least one active location.")

    has_table = db.scalar(
        select(DiningTable.id).where(
            DiningTable.tenant_id == tenant_id,
            DiningTable.location_id.in_(active_location_ids),
            DiningTable.is_enabled.is_(True),
        ).limit(1)
    )
    if not has_table:
        missing.append("Add at least one enabled dining table.")

    has_public_menu_item = db.scalar(
        select(MenuItem.id)
        .join(
            MenuCategory,
            (MenuCategory.id == MenuItem.category_id)
            & (MenuCategory.tenant_id == MenuItem.tenant_id)
            & (MenuCategory.location_id == MenuItem.location_id),
        )
        .where(
            MenuItem.tenant_id == tenant_id,
            MenuItem.location_id.in_(active_location_ids),
            MenuItem.available.is_(True),
            MenuCategory.is_active.is_(True),
        )
        .limit(1)
    )
    if not has_public_menu_item:
        missing.append("Add at least one available menu item in an active menu category.")
    return missing


@router.post("/register", response_model=RestaurantRegistrationOut, status_code=status.HTTP_201_CREATED)
def register_restaurant(payload: RestaurantRegistrationIn, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    _rate_limit(request)
    email = normalized_email(str(payload.owner_email))
    if db.scalar(select(StaffAccount.id).where(StaffAccount.email == email)):
        raise HTTPException(status_code=409, detail="Registration could not be completed with these details.")
    tenant = Tenant(name=payload.restaurant_name.strip(), slug=unique_tenant_slug(db, payload.restaurant_name), lifecycle=TenantLifecycle.PENDING_SETUP)
    db.add(tenant)
    try:
        db.flush()
        location = Location(tenant_id=tenant.id, name=payload.location_name.strip(), slug=unique_location_slug(db, tenant_id=tenant.id, name=payload.location_name), address=payload.address.strip())
        db.add(location)
        db.flush()
        db.add_all(OperatingHour(tenant_id=tenant.id, location_id=location.id, weekday=day, opens_at=time(9), closes_at=time(21)) for day in range(7))
        owner = StaffAccount(tenant_id=tenant.id, name=payload.owner_name.strip(), email=email, password_hash=hash_password(payload.password), invitation_status=InvitationStatus.ACCEPTED, is_active=True)
        db.add(owner)
        db.flush()
        db.add_all((StaffRoleAssignment(tenant_id=tenant.id, staff_id=owner.id, role=StaffRole.TENANT_OWNER), StaffLocationAssignment(tenant_id=tenant.id, location_id=location.id, staff_id=owner.id)))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Registration could not be completed with these details.") from None
    return {"tenant_slug": tenant.slug, "location_slug": location.slug, "lifecycle": tenant.lifecycle.value, "message": "Your restaurant is private until you complete setup and publish it."}


@router.post("/publish")
def publish_restaurant(
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> dict[str, str]:
    """Publish the current tenant once it has a usable public ordering setup."""
    if current.tenant_id is None:
        raise HTTPException(status_code=404, detail="Restaurant not found.")
    tenant = db.scalar(select(Tenant).where(Tenant.id == current.tenant_id).with_for_update())
    if tenant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found.")
    if tenant.lifecycle == TenantLifecycle.SUSPENDED:
        raise HTTPException(status_code=409, detail="A suspended restaurant cannot be published.")
    if tenant.lifecycle == TenantLifecycle.ACTIVE:
        return {"tenant_slug": tenant.slug, "lifecycle": tenant.lifecycle.value, "message": "Your restaurant is already published."}

    missing = _publish_readiness(db, tenant_id=tenant.id)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Complete the required setup before publishing your restaurant.",
                "missing": missing,
            },
        )
    tenant.lifecycle = TenantLifecycle.ACTIVE
    db.commit()
    return {"tenant_slug": tenant.slug, "lifecycle": tenant.lifecycle.value, "message": "Your restaurant is now published."}
