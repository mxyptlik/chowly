"""Authorized, location-scoped reporting routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import CurrentStaff
from app.db import get_db
from app.dependencies import assert_location_access, require_roles, scoped_resource_or_404
from app.models import Location, StaffRole
from app.report_schemas import OperationsReport
from app.reporting_service import InvalidReportRange, build_operations_report


router = APIRouter(prefix="/api/v1/staff/locations", tags=["reports"])


@router.get("/{location_id}/reports/operations", response_model=OperationsReport)
def operations_report(
    location_id: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    top_limit: int = Query(10, ge=1, le=100),
    current: CurrentStaff = Depends(
        require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)
    ),
    db: Session = Depends(get_db),
) -> OperationsReport:
    assert_location_access(current, location_id)
    location = scoped_resource_or_404(
        db, Location, location_id, current, location_id=location_id
    )
    if current.tenant_id is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    try:
        return build_operations_report(
            db,
            tenant_id=current.tenant_id,
            location=location,
            start_date=start_date,
            end_date=end_date,
            top_limit=top_limit,
        )
    except InvalidReportRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
