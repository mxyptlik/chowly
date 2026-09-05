"""Authentication and reusable authorization boundaries for protected routers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthenticationFailed, CurrentStaff, load_current_staff
from app.core.config import get_settings
from app.core.security import InvalidStaffSession, decode_staff_session
from app.db import get_db
from app.models import Customer, Location, QueueDestination, StaffRole


ModelT = TypeVar("ModelT")


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Staff authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _session_token(request: Request) -> str | None:
    settings = get_settings()
    cookie_token = request.cookies.get(settings.session_cookie_name)
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return cookie_token


def get_current_staff(request: Request, db: Session = Depends(get_db)) -> CurrentStaff:
    token = _session_token(request)
    if not token:
        raise _unauthorized()
    settings = get_settings()
    try:
        claims = decode_staff_session(token, secret=settings.session_signing_secret)
        return load_current_staff(
            db,
            claims.staff_id,
            expected_tenant_id=claims.tenant_id,
            active_location_id=claims.active_location_id,
        )
    except (InvalidStaffSession, AuthenticationFailed):
        raise _unauthorized() from None


def require_roles(*allowed_roles: StaffRole | str) -> Callable[..., CurrentStaff]:
    allowed = frozenset(StaffRole(role) for role in allowed_roles)

    def dependency(current: CurrentStaff = Depends(get_current_staff)) -> CurrentStaff:
        if not current.has_any_role(allowed):
            raise HTTPException(status_code=403, detail="This staff role cannot perform that action.")
        return current

    return dependency


def require_platform_admin(
    current: CurrentStaff = Depends(get_current_staff),
) -> CurrentStaff:
    if not current.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access is required.")
    return current


def assert_location_access(
    current: CurrentStaff,
    location_id: str,
    *,
    allow_platform_admin: bool = False,
) -> None:
    if location_id in current.location_ids:
        return
    if allow_platform_admin and current.is_platform_admin:
        return
    # A foreign or merely guessed location is deliberately non-enumerating.
    raise HTTPException(status_code=404, detail="Resource not found.")


def require_location_access(location_parameter: str = "location_id") -> Callable[..., CurrentStaff]:
    def dependency(
        request: Request,
        current: CurrentStaff = Depends(get_current_staff),
    ) -> CurrentStaff:
        location_id = request.path_params.get(location_parameter) or request.query_params.get(location_parameter)
        if not location_id:
            raise HTTPException(status_code=422, detail=f"Missing {location_parameter}.")
        assert_location_access(current, location_id)
        return current

    return dependency


def scoped_resource_or_404(
    db: Session,
    model: type[ModelT],
    resource_id: str,
    current: CurrentStaff,
    *,
    location_id: str | None = None,
) -> ModelT:
    """Load an ID only inside the authenticated tenant/location scope."""
    if current.tenant_id is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    predicates: list[Any] = [getattr(model, "id") == resource_id]
    if hasattr(model, "tenant_id"):
        predicates.append(getattr(model, "tenant_id") == current.tenant_id)
    if model is Location:
        predicates.append(Location.id.in_(current.location_ids))
    if location_id is not None:
        assert_location_access(current, location_id)
        if hasattr(model, "location_id"):
            predicates.append(getattr(model, "location_id") == location_id)
    elif hasattr(model, "location_id"):
        predicates.append(getattr(model, "location_id").in_(current.location_ids))
    resource = db.scalar(select(model).where(*predicates))
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return resource


def assert_order_operator(
    current: CurrentStaff,
    *,
    location_id: str,
    owner_id: str | None,
    allow_unowned_waiter: bool = False,
) -> None:
    assert_location_access(current, location_id)
    if StaffRole.MANAGER in current.roles:
        return
    if StaffRole.WAITER not in current.roles:
        raise HTTPException(status_code=403, detail="Waiter or manager access is required.")
    if owner_id == current.staff_id or (allow_unowned_waiter and owner_id is None):
        return
    raise HTTPException(status_code=403, detail="Only the order owner or a manager can perform that action.")


def assert_station_access(
    current: CurrentStaff,
    *,
    location_id: str,
    destination: QueueDestination | str,
) -> None:
    assert_location_access(current, location_id)
    normalized = QueueDestination(destination)
    required = StaffRole.CHEF if normalized == QueueDestination.KITCHEN else StaffRole.BARTENDER
    if required not in current.roles:
        raise HTTPException(status_code=403, detail="This preparation station is not assigned to this staff account.")


def can_view_customer_contact(
    current: CurrentStaff,
    *,
    location_id: str,
    order_owner_id: str | None,
) -> bool:
    if location_id not in current.location_ids:
        return False
    if StaffRole.MANAGER in current.roles:
        return True
    return StaffRole.WAITER in current.roles and order_owner_id == current.staff_id


def customer_contact_payload(
    current: CurrentStaff,
    *,
    location_id: str,
    order_owner_id: str | None,
    customer: Customer,
) -> dict[str, str | None] | None:
    if not can_view_customer_contact(
        current,
        location_id=location_id,
        order_owner_id=order_owner_id,
    ):
        return None
    return {"name": customer.name, "phone": customer.phone, "email": customer.email}
