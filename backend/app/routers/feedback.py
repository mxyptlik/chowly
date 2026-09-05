"""Public post-service feedback and manager-only complaint operations."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.auth import CurrentStaff
from app.core.security import hash_opaque_token
from app.db import get_db
from app.dependencies import assert_location_access, require_roles
from app.feedback_schemas import (
    ComplaintCreateIn,
    ComplaintListOut,
    ComplaintOut,
    ComplaintResolveIn,
    ItemRatingIn,
    OrderRatingIn,
    RatingOut,
)
from app.feedback_service import (
    FeedbackConflict,
    FeedbackInvalid,
    FeedbackNotFound,
    FeedbackNotReady,
    acknowledge_complaint,
    complaint_for_manager,
    complaint_order_line_id,
    complaint_prompt,
    create_complaint,
    create_item_rating,
    create_order_rating,
    list_complaints,
    resolve_complaint,
)
from app.models import Complaint, ComplaintStatus, Order, StaffRole


router = APIRouter(prefix="/api/v1", tags=["feedback"])


def _public_order_or_404(order_id: str, request: Request, db: Session) -> Order:
    raw_token = request.headers.get("X-Order-Access-Token") or request.query_params.get("access_token")
    order = db.get(Order, order_id)
    supplied_hash = hash_opaque_token(raw_token) if raw_token else ""
    if (
        order is None
        or not raw_token
        or not secrets.compare_digest(order.public_access_token_hash, supplied_hash)
    ):
        # Deliberately do not reveal whether an order ID or its token was wrong.
        raise HTTPException(status_code=404, detail="Order link not found.")
    return order


def require_public_order(
    order_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Order:
    return _public_order_or_404(order_id, request, db)


def _feedback_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FeedbackNotReady):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, FeedbackConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, FeedbackNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, FeedbackInvalid):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _rating_out(row, *, order_line_id: str | None = None) -> RatingOut:  # type: ignore[no-untyped-def]
    prompted, message = complaint_prompt(row.score)
    return RatingOut(
        id=row.id,
        order_id=row.order_id,
        order_line_id=order_line_id,
        score=row.score,
        comment=row.comment,
        created_at=row.created_at,
        complaint_prompt=prompted,
        complaint_prompt_message=message,
    )


def _complaint_out(db: Session, row: Complaint) -> ComplaintOut:
    return ComplaintOut(
        id=row.id,
        tenant_id=row.tenant_id,
        location_id=row.location_id,
        order_id=row.order_id,
        order_rating_id=row.order_rating_id,
        item_rating_id=row.item_rating_id,
        order_line_id=complaint_order_line_id(db, row),
        subject=row.subject,
        detail=row.detail,
        status=row.status,
        resolution_note=row.resolution_note,
        resolved_by_id=row.resolved_by_id,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "/public/orders/{order_id}/ratings/items",
    response_model=RatingOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_item_rating(
    payload: ItemRatingIn,
    order: Order = Depends(require_public_order),
    db: Session = Depends(get_db),
) -> RatingOut:
    try:
        row = create_item_rating(
            db,
            order=order,
            order_line_id=payload.order_line_id,
            score=payload.score,
            comment=payload.comment,
        )
    except (FeedbackNotReady, FeedbackConflict, FeedbackNotFound, FeedbackInvalid) as exc:
        raise _feedback_error(exc) from exc
    return _rating_out(row, order_line_id=row.order_line_id)


@router.post(
    "/public/orders/{order_id}/ratings/order",
    response_model=RatingOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_order_rating(
    payload: OrderRatingIn,
    order: Order = Depends(require_public_order),
    db: Session = Depends(get_db),
) -> RatingOut:
    try:
        row = create_order_rating(db, order=order, score=payload.score, comment=payload.comment)
    except (FeedbackNotReady, FeedbackConflict, FeedbackNotFound, FeedbackInvalid) as exc:
        raise _feedback_error(exc) from exc
    return _rating_out(row)


@router.post(
    "/public/orders/{order_id}/complaints",
    response_model=ComplaintOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_complaint(
    payload: ComplaintCreateIn,
    order: Order = Depends(require_public_order),
    db: Session = Depends(get_db),
) -> ComplaintOut:
    try:
        row = create_complaint(
            db,
            order=order,
            subject=payload.subject,
            detail=payload.detail,
            order_rating_id=payload.order_rating_id,
            item_rating_id=payload.item_rating_id,
        )
    except (FeedbackNotReady, FeedbackConflict, FeedbackNotFound, FeedbackInvalid) as exc:
        raise _feedback_error(exc) from exc
    return _complaint_out(db, row)


@router.get(
    "/staff/locations/{location_id}/complaints",
    response_model=ComplaintListOut,
)
def manager_complaints(
    location_id: str,
    complaint_status: Annotated[ComplaintStatus | None, Query(alias="status")] = None,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.MANAGER)),
) -> ComplaintListOut:
    assert_location_access(current, location_id)
    rows = list_complaints(
        db,
        tenant_id=current.tenant_id or "",
        location_id=location_id,
        status=complaint_status,
    )
    return ComplaintListOut(complaints=[_complaint_out(db, row) for row in rows])


@router.get(
    "/staff/locations/{location_id}/complaints/{complaint_id}",
    response_model=ComplaintOut,
)
def manager_complaint_detail(
    location_id: str,
    complaint_id: str,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.MANAGER)),
) -> ComplaintOut:
    assert_location_access(current, location_id)
    try:
        row = complaint_for_manager(
            db,
            complaint_id=complaint_id,
            tenant_id=current.tenant_id or "",
            location_id=location_id,
        )
    except FeedbackNotFound as exc:
        raise _feedback_error(exc) from exc
    return _complaint_out(db, row)


@router.post(
    "/staff/locations/{location_id}/complaints/{complaint_id}/acknowledge",
    response_model=ComplaintOut,
)
def manager_acknowledge_complaint(
    location_id: str,
    complaint_id: str,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.MANAGER)),
) -> ComplaintOut:
    assert_location_access(current, location_id)
    try:
        row = complaint_for_manager(
            db,
            complaint_id=complaint_id,
            tenant_id=current.tenant_id or "",
            location_id=location_id,
        )
        row = acknowledge_complaint(db, complaint=row, manager_id=current.staff_id)
    except (FeedbackNotFound, FeedbackConflict) as exc:
        raise _feedback_error(exc) from exc
    return _complaint_out(db, row)


@router.post(
    "/staff/locations/{location_id}/complaints/{complaint_id}/resolve",
    response_model=ComplaintOut,
)
def manager_resolve_complaint(
    location_id: str,
    complaint_id: str,
    payload: ComplaintResolveIn,
    db: Session = Depends(get_db),
    current: CurrentStaff = Depends(require_roles(StaffRole.MANAGER)),
) -> ComplaintOut:
    assert_location_access(current, location_id)
    try:
        row = complaint_for_manager(
            db,
            complaint_id=complaint_id,
            tenant_id=current.tenant_id or "",
            location_id=location_id,
        )
        row = resolve_complaint(
            db,
            complaint=row,
            manager_id=current.staff_id,
            resolution_note=payload.resolution_note,
            disposition=ComplaintStatus(payload.disposition),
        )
    except (FeedbackNotFound, FeedbackConflict, FeedbackInvalid) as exc:
        raise _feedback_error(exc) from exc
    return _complaint_out(db, row)

