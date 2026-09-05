"""Source-record reporting for one explicitly scoped restaurant location."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    Complaint,
    ComplaintStatus,
    ItemRating,
    LineStatus,
    Location,
    Order,
    OrderLine,
    OrderRating,
    OrderStatus,
    PaymentAttempt,
    PaymentMethod,
    PaymentStatus,
    Refund,
    RefundStatus,
    StaffRole,
    StaffRoleAssignment,
)
from app.report_schemas import (
    CancellationReport,
    ComplaintReport,
    DailyReportRow,
    DurationMetric,
    OperationsReport,
    OrderReport,
    PaymentMethodReport,
    PaymentsReport,
    PaymentStatusReport,
    RatingMetric,
    RatingsReport,
    RefundReport,
    ReportDateRange,
    TopItemReport,
    WaitTimesReport,
)


MONEY = Decimal("0.01")
ZERO = Decimal("0.00")


class InvalidReportRange(ValueError):
    pass


def _money(value: Decimal | int | float | None) -> Decimal:
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def local_date_bounds(
    location: Location, start_date: date, end_date: date
) -> tuple[datetime, datetime, ZoneInfo]:
    if end_date < start_date:
        raise InvalidReportRange("end_date must be on or after start_date.")
    if (end_date - start_date).days > 366:
        raise InvalidReportRange("A report range cannot exceed 367 days.")
    try:
        timezone = ZoneInfo(location.timezone)
    except ZoneInfoNotFoundError as exc:
        raise InvalidReportRange("The location timezone is invalid.") from exc
    start = datetime.combine(start_date, time.min, timezone).astimezone(UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, timezone).astimezone(UTC)
    return start, end, timezone


def _inside(value: datetime | None, start: datetime, end: datetime) -> bool:
    return value is not None and start <= _aware_utc(value) < end


def _transaction_time(created_at: datetime, completed_at: datetime | None) -> datetime:
    return _aware_utc(completed_at or created_at)


def _average_duration(pairs: list[tuple[datetime | None, datetime | None]]) -> DurationMetric:
    minutes = [
        (_aware_utc(end) - _aware_utc(start)).total_seconds() / 60
        for start, end in pairs
        if start is not None and end is not None and _aware_utc(end) >= _aware_utc(start)
    ]
    if not minutes:
        return DurationMetric()
    average = (Decimal(str(sum(minutes))) / Decimal(len(minutes))).quantize(
        MONEY, rounding=ROUND_HALF_UP
    )
    return DurationMetric(sample_count=len(minutes), average_minutes=average)


def _rating_metric(scores: list[int]) -> RatingMetric:
    distribution = {str(score): 0 for score in range(1, 6)}
    for score in scores:
        distribution[str(score)] += 1
    average = ZERO
    if scores:
        average = (Decimal(sum(scores)) / Decimal(len(scores))).quantize(
            MONEY, rounding=ROUND_HALF_UP
        )
    return RatingMetric(count=len(scores), average=average, distribution=distribution)


def _cancellation_actor(
    event: AuditEvent | None, staff_roles: dict[str, frozenset[StaffRole]]
) -> str:
    if event is None:
        return "UNKNOWN"
    if event.event_type == "ORDER_CANCELLED_BY_DINER" or event.actor_id is None:
        return "DINER"
    roles = staff_roles.get(event.actor_id, frozenset())
    if StaffRole.MANAGER in roles:
        return "MANAGER"
    if StaffRole.WAITER in roles:
        return "WAITER"
    return "STAFF"


def build_operations_report(
    db: Session,
    *,
    tenant_id: str,
    location: Location,
    start_date: date,
    end_date: date,
    top_limit: int = 10,
) -> OperationsReport:
    """Build a deterministic report without granting scope beyond the supplied location."""
    if location.tenant_id != tenant_id:
        raise InvalidReportRange("The report location does not belong to this tenant.")
    if location.currency != "NGN":
        raise InvalidReportRange("Chowly V1 reports support NGN locations only.")
    if not 1 <= top_limit <= 100:
        raise InvalidReportRange("top_limit must be between 1 and 100.")

    start_utc, end_utc, timezone = local_date_bounds(location, start_date, end_date)
    scope = (Order.tenant_id == tenant_id, Order.location_id == location.id)
    orders = list(
        db.scalars(
            select(Order).where(
                *scope, Order.created_at >= start_utc, Order.created_at < end_utc
            )
        )
    )

    payment_scope = (
        PaymentAttempt.tenant_id == tenant_id,
        PaymentAttempt.location_id == location.id,
    )
    payment_time = func.coalesce(PaymentAttempt.completed_at, PaymentAttempt.created_at)
    payments = list(
        db.scalars(
            select(PaymentAttempt).where(
                *payment_scope, payment_time >= start_utc, payment_time < end_utc
            )
        )
    )
    refund_scope = (Refund.tenant_id == tenant_id, Refund.location_id == location.id)
    refund_time = func.coalesce(Refund.completed_at, Refund.created_at)
    refunds = list(
        db.scalars(
            select(Refund).where(
                *refund_scope, refund_time >= start_utc, refund_time < end_utc
            )
        )
    )

    successful_payments = [p for p in payments if p.status == PaymentStatus.SUCCESSFUL]
    successful_refunds = [r for r in refunds if r.status == RefundStatus.SUCCESSFUL]
    gross = _money(sum((p.amount for p in successful_payments), ZERO))
    refund_total = _money(sum((r.amount for r in successful_refunds), ZERO))
    net = _money(gross - refund_total)

    days: dict[date, DailyReportRow] = {}
    cursor = start_date
    while cursor <= end_date:
        days[cursor] = DailyReportRow(date=cursor)
        cursor += timedelta(days=1)
    for order in orders:
        days[_aware_utc(order.created_at).astimezone(timezone).date()].order_count += 1
    for payment in successful_payments:
        local_day = _transaction_time(payment.created_at, payment.completed_at).astimezone(timezone).date()
        row = days[local_day]
        row.paid_order_count += 1
        row.gross_revenue = _money(row.gross_revenue + payment.amount)
    for refund in successful_refunds:
        local_day = _transaction_time(refund.created_at, refund.completed_at).astimezone(timezone).date()
        row = days[local_day]
        row.refund_total = _money(row.refund_total + refund.amount)
    for row in days.values():
        row.net_revenue = _money(row.gross_revenue - row.refund_total)

    order_statuses = {status.value: 0 for status in OrderStatus}
    for order in orders:
        order_statuses[order.status.value] += 1

    method_rows: list[PaymentMethodReport] = []
    for method in PaymentMethod:
        matching = [p for p in payments if p.method == method]
        successful = [p for p in matching if p.status == PaymentStatus.SUCCESSFUL]
        method_rows.append(
            PaymentMethodReport(
                method=method.value,
                attempt_count=len(matching),
                successful_count=len(successful),
                successful_amount=_money(sum((p.amount for p in successful), ZERO)),
            )
        )
    status_rows = [
        PaymentStatusReport(
            status=status.value,
            count=len(matching := [p for p in payments if p.status == status]),
            amount=_money(sum((p.amount for p in matching), ZERO)),
        )
        for status in PaymentStatus
    ]
    refund_statuses = {status.value: 0 for status in RefundStatus}
    for refund in refunds:
        refund_statuses[refund.status.value] += 1

    paid_order_ids = {payment.order_id for payment in successful_payments}
    top_counts: dict[str, tuple[int, Decimal]] = defaultdict(lambda: (0, ZERO))
    if paid_order_ids:
        lines = db.scalars(
            select(OrderLine).where(
                OrderLine.tenant_id == tenant_id,
                OrderLine.location_id == location.id,
                OrderLine.order_id.in_(paid_order_ids),
                OrderLine.status != LineStatus.CANCELLED,
            )
        )
        for line in lines:
            quantity, revenue = top_counts[line.item_name_snapshot]
            top_counts[line.item_name_snapshot] = (
                quantity + line.quantity,
                revenue + line.total_amount,
            )
    top_items = [
        TopItemReport(item_name=name, quantity=quantity, paid_revenue=_money(revenue))
        for name, (quantity, revenue) in sorted(
            top_counts.items(), key=lambda item: (-item[1][0], -item[1][1], item[0])
        )[:top_limit]
    ]

    cancelled_orders = list(
        db.scalars(
            select(Order).where(
                *scope,
                Order.cancelled_at.is_not(None),
                Order.cancelled_at >= start_utc,
                Order.cancelled_at < end_utc,
            )
        )
    )
    cancel_ids = {order.id for order in cancelled_orders}
    events: list[AuditEvent] = []
    if cancel_ids:
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.location_id == location.id,
                    AuditEvent.subject_type == "ORDER",
                    AuditEvent.subject_id.in_(cancel_ids),
                    AuditEvent.event_type.in_(("ORDER_CANCELLED", "ORDER_CANCELLED_BY_DINER")),
                )
                .order_by(AuditEvent.created_at.desc())
            )
        )
    event_by_order: dict[str, AuditEvent] = {}
    for event in events:
        event_by_order.setdefault(event.subject_id, event)
    actor_ids = {event.actor_id for event in events if event.actor_id}
    staff_roles: dict[str, frozenset[StaffRole]] = {}
    if actor_ids:
        role_rows = db.execute(
            select(StaffRoleAssignment.staff_id, StaffRoleAssignment.role).where(
                StaffRoleAssignment.tenant_id == tenant_id,
                StaffRoleAssignment.staff_id.in_(actor_ids),
            )
        )
        grouped_roles: dict[str, set[StaffRole]] = defaultdict(set)
        for staff_id, role in role_rows:
            grouped_roles[staff_id].add(role)
        staff_roles = {key: frozenset(value) for key, value in grouped_roles.items()}
    actor_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for order in cancelled_orders:
        event = event_by_order.get(order.id)
        actor_counts[_cancellation_actor(event, staff_roles)] += 1
        before = event.before_data if event and event.before_data else {}
        stage = before.get("status", "UNKNOWN")
        stage_counts[getattr(stage, "value", str(stage))] += 1
        reason = (order.cancellation_reason or "UNSPECIFIED").strip() or "UNSPECIFIED"
        reason_counts[reason] += 1

    complaint_rows = list(
        db.scalars(
            select(Complaint).where(
                Complaint.tenant_id == tenant_id,
                Complaint.location_id == location.id,
                Complaint.created_at >= start_utc,
                Complaint.created_at < end_utc,
            )
        )
    )
    complaint_statuses = {status.value: 0 for status in ComplaintStatus}
    for complaint in complaint_rows:
        complaint_statuses[complaint.status.value] += 1
    resolved_pairs = [
        (complaint.created_at, complaint.resolved_at)
        for complaint in complaint_rows
        if complaint.resolved_at is not None
    ]
    resolution = _average_duration(resolved_pairs)
    resolution_hours = (resolution.average_minutes / Decimal(60)).quantize(
        MONEY, rounding=ROUND_HALF_UP
    ) if resolution.sample_count else ZERO

    order_scores = list(
        db.scalars(
            select(OrderRating.score).where(
                OrderRating.tenant_id == tenant_id,
                OrderRating.location_id == location.id,
                OrderRating.created_at >= start_utc,
                OrderRating.created_at < end_utc,
            )
        )
    )
    item_scores = list(
        db.scalars(
            select(ItemRating.score).where(
                ItemRating.tenant_id == tenant_id,
                ItemRating.location_id == location.id,
                ItemRating.created_at >= start_utc,
                ItemRating.created_at < end_utc,
            )
        )
    )

    return OperationsReport(
        location_id=location.id,
        currency=location.currency,
        timezone=location.timezone,
        date_range=ReportDateRange(
            start_date=start_date,
            end_date=end_date,
            start_utc=start_utc,
            end_utc_exclusive=end_utc,
        ),
        daily=list(days.values()),
        orders=OrderReport(
            total=len(orders),
            paid_orders=len({p.order_id for p in successful_payments}),
            by_status=order_statuses,
            gross_revenue=gross,
            refund_total=refund_total,
            net_revenue=net,
        ),
        payments=PaymentsReport(
            total_attempts=len(payments),
            methods=method_rows,
            statuses=status_rows,
            refunds=RefundReport(
                attempt_count=len(refunds),
                successful_count=len(successful_refunds),
                successful_total=refund_total,
                by_status=refund_statuses,
            ),
        ),
        wait_times=WaitTimesReport(
            acceptance=_average_duration([(o.created_at, o.accepted_at) for o in orders]),
            preparation=_average_duration([(o.accepted_at, o.ready_at) for o in orders]),
            ready_to_serve=_average_duration([(o.ready_at, o.served_at) for o in orders]),
            total=_average_duration([(o.created_at, o.served_at) for o in orders]),
        ),
        top_items=top_items,
        cancellations=CancellationReport(
            total=len(cancelled_orders),
            by_actor=dict(sorted(actor_counts.items())),
            by_stage=dict(sorted(stage_counts.items())),
            by_reason=dict(sorted(reason_counts.items())),
        ),
        complaints=ComplaintReport(
            total=len(complaint_rows),
            by_status=complaint_statuses,
            resolved_count=resolution.sample_count,
            average_resolution_hours=resolution_hours,
        ),
        ratings=RatingsReport(
            orders=_rating_metric(order_scores),
            items=_rating_metric(item_scores),
        ),
    )
