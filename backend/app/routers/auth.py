"""Invitation-created staff account and same-site session endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    AuthenticationFailed,
    CurrentStaff,
    InvitationConflict,
    InvitationExpired,
    InvitationInvalid,
    StaffAssignmentInvalid,
    StaffAssignmentNotFound,
    accept_invitation,
    authenticate_staff,
    create_invitation,
    current_staff_from_account,
    tenant_staff_accounts,
    update_staff_assignments,
)
from app.auth_schemas import (
    ActiveLocationIn,
    DemoSessionIn,
    RealtimeGrantIn,
    RealtimeGrantOut,
    StaffInviteAcceptIn,
    StaffInviteIn,
    StaffInviteOut,
    StaffAssignmentOut,
    StaffAssignmentUpdateIn,
    StaffLocationOut,
    StaffLoginIn,
    StaffSessionOut,
)
from app.core.config import get_settings
from app.core.security import issue_staff_session
from app.db import get_db
from app.dependencies import assert_location_access, get_current_staff, require_roles
from app.events import RealtimeGrant, RealtimeTokenCodec
from app.models import Location, StaffAccount, StaffRole


router = APIRouter(prefix="/api/v1/staff/auth", tags=["staff-auth"])


def _session_out(current: CurrentStaff) -> StaffSessionOut:
    return StaffSessionOut(
        staff_id=current.staff_id,
        name=current.account.name,
        email=current.account.email or "",
        roles=sorted(current.roles, key=lambda role: role.value),
        locations=[
            StaffLocationOut(id=location.id, tenant_id=location.tenant_id, name=location.name)
            for location in current.locations
        ],
        active_tenant_id=current.tenant_id,
        active_location_id=current.active_location_id,
    )


def _set_session_cookie(response: Response, current: CurrentStaff) -> None:
    settings = get_settings()
    ttl = timedelta(minutes=settings.session_ttl_minutes)
    token = issue_staff_session(
        staff_id=current.staff_id,
        tenant_id=current.tenant_id,
        active_location_id=current.active_location_id,
        secret=settings.session_signing_secret,
        ttl=ttl,
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/api/v1",
    )


def _staff_assignment_out(account: StaffAccount, db: Session) -> StaffAssignmentOut:
    location_ids = {assignment.location_id for assignment in account.location_assignments}
    locations_by_id = {
        location.id: location
        for location in db.scalars(
            select(Location).where(Location.id.in_(location_ids))
        )
    } if location_ids else {}
    return StaffAssignmentOut(
        id=account.id,
        name=account.name,
        email=account.email,
        invitation_status=account.invitation_status.value,
        is_active=account.is_active,
        roles=sorted((assignment.role for assignment in account.role_assignments), key=lambda role: role.value),
        locations=[
            StaffLocationOut(id=location.id, tenant_id=location.tenant_id, name=location.name)
            for location in sorted(locations_by_id.values(), key=lambda item: (item.name, item.id))
        ],
    )
@router.post("/login", response_model=StaffSessionOut)
def login(
    payload: StaffLoginIn,
    response: Response,
    db: Session = Depends(get_db),
) -> StaffSessionOut:
    try:
        account = authenticate_staff(db, str(payload.email), payload.password)
    except AuthenticationFailed:
        raise HTTPException(status_code=401, detail="Invalid email or password.") from None
    current = current_staff_from_account(db, account)
    _set_session_cookie(response, current)
    return _session_out(current)

@router.post("/demo-session", response_model=StaffSessionOut)
def create_demo_session(
    payload: DemoSessionIn,
    response: Response,
    db: Session = Depends(get_db),
) -> StaffSessionOut:
    """
    Issue a normal staff session for one predefined assessor persona.

    This endpoint is unavailable unless CHOWLY_DEMO_MODE=true.
    It never exposes the demo password and never permits PLATFORM_ADMIN.
    """
    settings = get_settings()

    if not settings.demo_mode:
        raise HTTPException(
            status_code=404,
            detail="Demo access is not enabled.",
        )

    role = StaffRole(payload.persona)

    email = (
        f"pilot{settings.demo_tenant_ordinal}."
        f"{role.value.lower()}@demo.chowly.ng"
    )

    account = db.scalar(
        select(StaffAccount).where(
            StaffAccount.email == email
        )
    )

    if account is None or not account.is_active:
        raise HTTPException(
            status_code=503,
            detail="The requested demo persona is unavailable.",
        )

    current = current_staff_from_account(db, account)

    if role not in current.roles:
        raise HTTPException(
            status_code=503,
            detail="The requested demo persona is not configured correctly.",
        )

    _set_session_cookie(response, current)

    return _session_out(current)

@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/api/v1")


@router.get("/session", response_model=StaffSessionOut)
def session(current: CurrentStaff = Depends(get_current_staff)) -> StaffSessionOut:
    return _session_out(current)


@router.post("/refresh", response_model=StaffSessionOut)
def refresh(
    response: Response,
    current: CurrentStaff = Depends(get_current_staff),
) -> StaffSessionOut:
    _set_session_cookie(response, current)
    return _session_out(current)


@router.post("/active-location", response_model=StaffSessionOut)
def set_active_location(
    payload: ActiveLocationIn,
    response: Response,
    current: CurrentStaff = Depends(get_current_staff),
) -> StaffSessionOut:
    assert_location_access(current, payload.location_id)
    selected = CurrentStaff(
        account=current.account,
        tenant_id=current.tenant_id,
        roles=current.roles,
        location_ids=current.location_ids,
        active_location_id=payload.location_id,
        locations=current.locations,
    )
    _set_session_cookie(response, selected)
    return _session_out(selected)


@router.post("/invitations", response_model=StaffInviteOut, status_code=201)
def invite_staff(
    payload: StaffInviteIn,
    db: Session = Depends(get_db),
    inviter: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
) -> StaffInviteOut:
    settings = get_settings()
    try:
        account, raw_token = create_invitation(
            db,
            inviter=inviter,
            name=payload.name,
            email=str(payload.email),
            roles=payload.roles,
            location_ids=payload.location_ids,
            ttl=timedelta(hours=settings.invitation_ttl_hours),
        )
    except InvitationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except InvitationInvalid as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    assert account.invitation_expires_at is not None
    return StaffInviteOut(
        staff_id=account.id,
        email=account.email or "",
        expires_at=account.invitation_expires_at,
        acceptance_token=raw_token,
    )


@router.get("/members", response_model=list[StaffAssignmentOut])
def list_tenant_staff(
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> list[StaffAssignmentOut]:
    if current.tenant_id is None:
        raise HTTPException(status_code=403, detail="Restaurant tenant access is required.")
    return [_staff_assignment_out(account, db) for account in tenant_staff_accounts(db, tenant_id=current.tenant_id)]


@router.get("/members/{staff_id}", response_model=StaffAssignmentOut)
def get_tenant_staff_member(
    staff_id: str,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> StaffAssignmentOut:
    if current.tenant_id is None:
        raise HTTPException(status_code=403, detail="Restaurant tenant access is required.")
    account = next((row for row in tenant_staff_accounts(db, tenant_id=current.tenant_id) if row.id == staff_id), None)
    if account is None:
        raise HTTPException(status_code=404, detail="Staff member not found.")
    return _staff_assignment_out(account, db)


@router.put("/members/{staff_id}/assignments", response_model=StaffAssignmentOut)
def replace_tenant_staff_assignments(
    staff_id: str,
    payload: StaffAssignmentUpdateIn,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> StaffAssignmentOut:
    try:
        account = update_staff_assignments(
            db,
            actor=current,
            target_staff_id=staff_id,
            roles=payload.roles,
            location_ids=payload.location_ids,
        )
    except StaffAssignmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except StaffAssignmentInvalid as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _staff_assignment_out(account, db)


@router.post("/invitations/accept", response_model=StaffSessionOut)
def accept_staff_invitation(
    payload: StaffInviteAcceptIn,
    response: Response,
    db: Session = Depends(get_db),
) -> StaffSessionOut:
    try:
        account = accept_invitation(db, raw_token=payload.token, password=payload.password)
    except InvitationExpired as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from None
    except InvitationInvalid as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    current = current_staff_from_account(db, account)
    _set_session_cookie(response, current)
    return _session_out(current)


@router.post("/realtime-grant", response_model=RealtimeGrantOut)
def issue_realtime_grant(
    payload: RealtimeGrantIn,
    current: CurrentStaff = Depends(get_current_staff),
) -> RealtimeGrantOut:
    assert_location_access(current, payload.location_id)
    if payload.role not in current.roles:
        raise HTTPException(status_code=403, detail="This realtime role is not assigned to this staff account.")
    if current.tenant_id is None:
        raise HTTPException(status_code=403, detail="Restaurant location access is required.")
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    settings = get_settings()
    token = RealtimeTokenCodec(settings.realtime_signing_secret).encode(
        RealtimeGrant(
            kind="staff",
            expires_at=int(expires_at.timestamp()),
            tenant_id=current.tenant_id,
            location_ids=[payload.location_id],
            roles=[payload.role.value],
        )
    )
    return RealtimeGrantOut(
        token=token,
        expires_at=expires_at,
        tenant_id=current.tenant_id,
        location_id=payload.location_id,
        role=payload.role,
    )
