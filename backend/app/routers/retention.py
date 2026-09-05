"""Tenant-owner retention policy and platform exception approval routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import CurrentStaff
from app.db import get_db
from app.dependencies import require_platform_admin, require_roles
from app.models import StaffRole, Tenant
from app.retention_schemas import RetentionConfigureIn, RetentionPolicyOut
from app.retention_service import (
    RetentionConflict,
    RetentionError,
    approve_pending_extension,
    configure_retention,
    policy_payload,
)


router = APIRouter(prefix="/api/v1", tags=["retention"])


def _current_tenant(db: Session, current: CurrentStaff) -> Tenant:
    tenant = db.get(Tenant, current.tenant_id) if current.tenant_id else None
    if tenant is None:
        raise HTTPException(status_code=404, detail="Restaurant tenant not found.")
    return tenant


@router.get("/staff/tenant/retention", response_model=RetentionPolicyOut)
def get_tenant_retention(
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> dict:
    return policy_payload(_current_tenant(db, current))


@router.put("/staff/tenant/retention", response_model=RetentionPolicyOut)
def set_tenant_retention(
    payload: RetentionConfigureIn,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER)),
) -> dict:
    tenant = _current_tenant(db, current)
    try:
        configure_retention(db, tenant=tenant, requested_days=payload.days)
    except RetentionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return policy_payload(tenant)


@router.post(
    "/platform/tenants/{tenant_id}/retention/approve",
    response_model=RetentionPolicyOut,
)
def approve_tenant_retention(
    tenant_id: str,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_platform_admin),
) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Restaurant tenant not found.")
    try:
        approve_pending_extension(db, tenant=tenant, platform_admin_id=current.staff_id)
    except RetentionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return policy_payload(tenant)

