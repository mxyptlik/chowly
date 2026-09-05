"""Post-service feedback domain rules, independent of HTTP transport."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    Complaint,
    ComplaintStatus,
    ItemRating,
    LineStatus,
    Order,
    OrderLine,
    OrderRating,
    OrderStatus,
)


POST_SERVICE_STATUSES = frozenset({OrderStatus.SERVED, OrderStatus.PAID})
LOW_RATING_SCORES = frozenset({1, 2})
LOW_RATING_PROMPT = "Would you like to tell the restaurant manager what went wrong?"


class FeedbackError(ValueError):
    """Base class for a feedback rule violation."""


class FeedbackNotReady(FeedbackError):
    pass


class FeedbackConflict(FeedbackError):
    pass


class FeedbackNotFound(FeedbackError):
    pass


class FeedbackInvalid(FeedbackError):
    pass


def ensure_post_service(order: Order) -> None:
    if order.status not in POST_SERVICE_STATUSES:
        raise FeedbackNotReady("Feedback and complaints are available only after the order is served.")


def complaint_prompt(score: int) -> tuple[bool, str | None]:
    prompted = score in LOW_RATING_SCORES
    return prompted, LOW_RATING_PROMPT if prompted else None


def create_item_rating(
    db: Session,
    *,
    order: Order,
    order_line_id: str,
    score: int,
    comment: str | None,
) -> ItemRating:
    ensure_post_service(order)
    line = db.scalar(
        select(OrderLine).where(
            OrderLine.id == order_line_id,
            OrderLine.order_id == order.id,
            OrderLine.tenant_id == order.tenant_id,
            OrderLine.location_id == order.location_id,
        )
    )
    if line is None or line.status == LineStatus.CANCELLED:
        raise FeedbackNotFound("A rateable food or drink line was not found on this order.")
    if db.scalar(select(ItemRating.id).where(ItemRating.order_line_id == line.id)):
        raise FeedbackConflict("This order line has already been rated.")
    row = ItemRating(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        order_id=order.id,
        order_line_id=line.id,
        customer_id=order.customer_id,
        score=score,
        comment=comment,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise FeedbackConflict("This order line has already been rated.") from exc
    db.refresh(row)
    return row


def create_order_rating(
    db: Session,
    *,
    order: Order,
    score: int,
    comment: str | None,
) -> OrderRating:
    ensure_post_service(order)
    if db.scalar(select(OrderRating.id).where(OrderRating.order_id == order.id)):
        raise FeedbackConflict("This order has already been rated.")
    row = OrderRating(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        order_id=order.id,
        customer_id=order.customer_id,
        score=score,
        comment=comment,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise FeedbackConflict("This order has already been rated.") from exc
    db.refresh(row)
    return row


def create_complaint(
    db: Session,
    *,
    order: Order,
    subject: str,
    detail: str,
    order_rating_id: str | None = None,
    item_rating_id: str | None = None,
) -> Complaint:
    ensure_post_service(order)
    if order_rating_id:
        rating = db.scalar(
            select(OrderRating).where(
                OrderRating.id == order_rating_id,
                OrderRating.order_id == order.id,
                OrderRating.customer_id == order.customer_id,
                OrderRating.tenant_id == order.tenant_id,
                OrderRating.location_id == order.location_id,
            )
        )
        if rating is None:
            raise FeedbackNotFound("The order rating was not found for this order.")
    if item_rating_id:
        rating = db.scalar(
            select(ItemRating).where(
                ItemRating.id == item_rating_id,
                ItemRating.order_id == order.id,
                ItemRating.customer_id == order.customer_id,
                ItemRating.tenant_id == order.tenant_id,
                ItemRating.location_id == order.location_id,
            )
        )
        if rating is None:
            raise FeedbackNotFound("The item rating was not found for this order.")
    row = Complaint(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        order_id=order.id,
        customer_id=order.customer_id,
        order_rating_id=order_rating_id,
        item_rating_id=item_rating_id,
        subject=subject,
        detail=detail,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_complaints(
    db: Session,
    *,
    tenant_id: str,
    location_id: str,
    status: ComplaintStatus | None = None,
) -> list[Complaint]:
    query = select(Complaint).where(
        Complaint.tenant_id == tenant_id,
        Complaint.location_id == location_id,
    )
    if status is not None:
        query = query.where(Complaint.status == status)
    return list(db.scalars(query.order_by(Complaint.created_at.desc(), Complaint.id.desc())))


def complaint_for_manager(
    db: Session,
    *,
    complaint_id: str,
    tenant_id: str,
    location_id: str,
) -> Complaint:
    complaint = db.scalar(
        select(Complaint).where(
            Complaint.id == complaint_id,
            Complaint.tenant_id == tenant_id,
            Complaint.location_id == location_id,
        )
    )
    if complaint is None:
        raise FeedbackNotFound("Complaint not found.")
    return complaint


def acknowledge_complaint(db: Session, *, complaint: Complaint, manager_id: str) -> Complaint:
    if complaint.status != ComplaintStatus.OPEN:
        raise FeedbackConflict("Only open complaints can be acknowledged.")
    before = {"status": complaint.status.value}
    complaint.status = ComplaintStatus.IN_REVIEW
    complaint.updated_at = datetime.now(UTC)
    db.add(
        AuditEvent(
            tenant_id=complaint.tenant_id,
            location_id=complaint.location_id,
            actor_id=manager_id,
            event_type="COMPLAINT_ACKNOWLEDGED",
            subject_type="COMPLAINT",
            subject_id=complaint.id,
            detail="Complaint acknowledged by manager.",
            before_data=before,
            after_data={"status": complaint.status.value},
        )
    )
    db.commit()
    db.refresh(complaint)
    return complaint


def resolve_complaint(
    db: Session,
    *,
    complaint: Complaint,
    manager_id: str,
    resolution_note: str,
    disposition: ComplaintStatus,
) -> Complaint:
    if disposition not in {ComplaintStatus.RESOLVED, ComplaintStatus.DISMISSED}:
        raise FeedbackInvalid("Complaint disposition must be resolved or dismissed.")
    if complaint.status in {ComplaintStatus.RESOLVED, ComplaintStatus.DISMISSED}:
        raise FeedbackConflict("This complaint is already closed.")
    before = {
        "status": complaint.status.value,
        "resolution_note": complaint.resolution_note,
        "resolved_by_id": complaint.resolved_by_id,
    }
    now = datetime.now(UTC)
    complaint.status = disposition
    complaint.resolution_note = resolution_note
    complaint.resolved_by_id = manager_id
    complaint.resolved_at = now
    complaint.updated_at = now
    db.add(
        AuditEvent(
            tenant_id=complaint.tenant_id,
            location_id=complaint.location_id,
            actor_id=manager_id,
            event_type=f"COMPLAINT_{disposition.value}",
            subject_type="COMPLAINT",
            subject_id=complaint.id,
            detail=resolution_note,
            before_data=before,
            after_data={
                "status": complaint.status.value,
                "resolution_note": complaint.resolution_note,
                "resolved_by_id": complaint.resolved_by_id,
                "resolved_at": now.isoformat(),
            },
        )
    )
    db.commit()
    db.refresh(complaint)
    return complaint


def complaint_order_line_id(db: Session, complaint: Complaint) -> str | None:
    if not complaint.item_rating_id:
        return None
    return db.scalar(select(ItemRating.order_line_id).where(ItemRating.id == complaint.item_rating_id))

