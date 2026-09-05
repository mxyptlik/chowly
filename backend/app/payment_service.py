"""Payment boundary for Chowly's deterministic V1 provider simulation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentStaff
from app.dependencies import assert_location_access, assert_order_operator
from app.events import (
    EventDraft,
    EventResource,
    EventScope,
    EventType,
    ResourceKind,
    public_order_channel,
    staff_channel,
    stage_domain_event,
)
from app.models import (
    DiningTable,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentMethod,
    PaymentStatus,
    Refund,
    RefundStatus,
    StaffRole,
    TableVisit,
    uid,
)
from app.order_service import OrderDomainError, add_audit, stage_order_changed, stage_table_changed, touch
from app.qr_service import synchronize_table_activity


MockScenario = Literal["APPROVED", "DECLINED", "TEMPORARY_FAILURE"]


def _as_utc(value: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC value at the API boundary.

    PostgreSQL preserves ``DateTime(timezone=True)`` offsets, while SQLite returns
    the same fields without a ``tzinfo`` value.  Normalising here keeps payment and
    refund representations identical across both supported local test databases.
    """

    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    successful: bool
    reference: str
    code: str
    message: str | None = None
    retryable: bool = False


class PaymentProvider(Protocol):
    def charge(
        self,
        *,
        order_id: str,
        method: PaymentMethod,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        scenario: MockScenario,
    ) -> ProviderResult: ...


class DeterministicMockPaymentProvider:
    """No-network provider with reproducible references and controlled outcomes."""

    def charge(
        self,
        *,
        order_id: str,
        method: PaymentMethod,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        scenario: MockScenario,
    ) -> ProviderResult:
        digest = hashlib.sha256(
            f"{order_id}:{method.value}:{amount:.2f}:{currency}:{idempotency_key}".encode()
        ).hexdigest()[:24]
        reference = f"mock-{digest}"
        if scenario == "DECLINED":
            return ProviderResult(False, reference, "DECLINED", "Mock payment declined.")
        if scenario == "TEMPORARY_FAILURE":
            return ProviderResult(
                False,
                reference,
                "TEMPORARY_FAILURE",
                "Mock provider is temporarily unavailable.",
                retryable=True,
            )
        return ProviderResult(True, reference, "APPROVED")


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def _idempotency_key(raw: str | None) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise OrderDomainError("Idempotency-Key is required.", status_code=422)
    if len(cleaned) > 100:
        raise OrderDomainError("Idempotency-Key is too long.", status_code=422)
    return cleaned


def _validate_client_totals(
    order: Order, *, amount: Decimal | None, currency: str | None
) -> None:
    if amount is not None and _money(amount) != _money(order.total_amount):
        raise OrderDomainError("Payment amount does not match the order total.", status_code=409)
    if currency is not None and currency.upper() != order.currency.upper():
        raise OrderDomainError("Payment currency does not match the order currency.", status_code=409)


def _lock_order(db: Session, order: Order) -> Order:
    locked = db.scalar(select(Order).where(Order.id == order.id).with_for_update())
    if locked is None:
        raise OrderDomainError("Order link not found.", status_code=404)
    return locked


def _successful_payment(db: Session, order_id: str) -> PaymentAttempt | None:
    return db.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.order_id == order_id,
            PaymentAttempt.status == PaymentStatus.SUCCESSFUL,
        )
    )


def _existing_attempt(db: Session, key: str) -> PaymentAttempt | None:
    return db.scalar(select(PaymentAttempt).where(PaymentAttempt.idempotency_key == key))


def _assert_same_attempt(
    attempt: PaymentAttempt,
    *,
    order: Order,
    method: PaymentMethod,
) -> None:
    if (
        attempt.order_id != order.id
        or attempt.method != method
        or _money(attempt.amount) != _money(order.total_amount)
        or attempt.currency != order.currency
    ):
        raise OrderDomainError("Idempotency-Key was already used for another payment.", status_code=409)


def _stage_payment_event(db: Session, order: Order, attempt: PaymentAttempt) -> None:
    draft = EventDraft(
        type=EventType.PAYMENT_CHANGED,
        scope=EventScope(
            tenant_id=order.tenant_id,
            location_id=order.location_id,
            order_id=order.id,
        ),
        resource=EventResource(kind=ResourceKind.PAYMENT, id=attempt.id),
        payload={
            "order_id": order.id,
            "status": attempt.status.value,
            "method": attempt.method.value,
            "order_status": order.status.value,
        },
    )
    for role in (StaffRole.MANAGER, StaffRole.WAITER):
        stage_domain_event(
            db,
            staff_channel(order.tenant_id, order.location_id, role.value),
            draft,
        )
    stage_domain_event(db, public_order_channel(order.id), draft)


def _mark_paid(
    db: Session,
    *,
    order: Order,
    attempt: PaymentAttempt,
    actor_id: str | None,
) -> None:
    now = attempt.completed_at or datetime.now(UTC)
    order.status = OrderStatus.PAID
    order.paid_at = now
    touch(order, now=now)
    add_audit(
        db,
        order=order,
        event_type="ORDER_PAYMENT_RECORDED",
        actor_id=actor_id,
        reason="Staff-recorded cash" if actor_id else "Mock online payment",
        before={"status": OrderStatus.SERVED},
        after={
            "status": OrderStatus.PAID,
            "payment_attempt_id": attempt.id,
            "method": attempt.method,
            "amount": attempt.amount,
            "currency": attempt.currency,
        },
        request_id=attempt.idempotency_key,
    )
    if order.visit_id:
        visit = db.get(TableVisit, order.visit_id)
        if visit and visit.closed_at is None:
            has_other_active = db.scalar(
                select(Order.id).where(
                    Order.visit_id == visit.id,
                    Order.id != order.id,
                    Order.status.not_in((OrderStatus.PAID, OrderStatus.CANCELLED)),
                ).limit(1)
            )
            if not has_other_active:
                visit.closed_at = now
    if order.table_id:
        table = db.get(DiningTable, order.table_id)
        if table:
            db.flush()
            synchronize_table_activity(db, table)
            stage_table_changed(db, table, change="payment_terminal_state")
    stage_order_changed(db, order, change="paid")
    _stage_payment_event(db, order, attempt)


def create_online_payment(
    db: Session,
    *,
    order: Order,
    method: PaymentMethod,
    amount: Decimal | None,
    currency: str | None,
    scenario: MockScenario,
    idempotency_key: str | None,
    provider: PaymentProvider,
) -> tuple[PaymentAttempt, bool]:
    if method == PaymentMethod.CASH:
        raise OrderDomainError("Cash cannot be selected through the public payment route.", status_code=403)
    key = _idempotency_key(idempotency_key)
    order = _lock_order(db, order)
    _validate_client_totals(order, amount=amount, currency=currency)
    existing = _existing_attempt(db, key)
    if existing:
        _assert_same_attempt(existing, order=order, method=method)
        return existing, True
    winner = _successful_payment(db, order.id)
    if winner:
        return winner, True
    if order.status != OrderStatus.SERVED:
        raise OrderDomainError("Only a served order can be paid.", status_code=409)

    result = provider.charge(
        order_id=order.id,
        method=method,
        amount=_money(order.total_amount),
        currency=order.currency,
        idempotency_key=key,
        scenario=scenario,
    )
    now = datetime.now(UTC)
    attempt = PaymentAttempt(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        order_id=order.id,
        method=method,
        amount=_money(order.total_amount),
        currency=order.currency,
        status=PaymentStatus.SUCCESSFUL if result.successful else PaymentStatus.FAILED,
        reference=result.reference,
        provider_code=result.code,
        failure_reason=result.message,
        idempotency_key=key,
        completed_at=now,
    )
    db.add(attempt)
    db.flush()
    if result.successful:
        _mark_paid(db, order=order, attempt=attempt, actor_id=None)
    else:
        add_audit(
            db,
            order=order,
            event_type="ORDER_PAYMENT_FAILED",
            actor_id=None,
            reason=result.message or result.code,
            after={"payment_attempt_id": attempt.id, "provider_code": result.code},
            request_id=key,
        )
        _stage_payment_event(db, order, attempt)
    return attempt, False


def record_cash_payment(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    amount: Decimal | None,
    currency: str | None,
    idempotency_key: str | None,
) -> tuple[PaymentAttempt, bool]:
    key = _idempotency_key(idempotency_key)
    assert_order_operator(current, location_id=order.location_id, owner_id=order.owner_id)
    order = _lock_order(db, order)
    _validate_client_totals(order, amount=amount, currency=currency)
    existing = _existing_attempt(db, key)
    if existing:
        _assert_same_attempt(existing, order=order, method=PaymentMethod.CASH)
        return existing, True
    winner = _successful_payment(db, order.id)
    if winner:
        return winner, True
    if order.status != OrderStatus.SERVED:
        raise OrderDomainError("Only a served order can be paid.", status_code=409)
    now = datetime.now(UTC)
    digest = hashlib.sha256(f"cash:{order.id}:{key}".encode()).hexdigest()[:24]
    attempt = PaymentAttempt(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        order_id=order.id,
        method=PaymentMethod.CASH,
        amount=_money(order.total_amount),
        currency=order.currency,
        status=PaymentStatus.SUCCESSFUL,
        reference=f"cash-{digest}",
        provider_code="STAFF_RECORDED",
        idempotency_key=key,
        recorded_by_id=current.staff_id,
        completed_at=now,
    )
    db.add(attempt)
    db.flush()
    _mark_paid(db, order=order, attempt=attempt, actor_id=current.staff_id)
    return attempt, False


def refund_full_payment(
    db: Session,
    *,
    order: Order,
    current: CurrentStaff,
    reason: str,
    idempotency_key: str | None,
) -> tuple[Refund, bool]:
    assert_location_access(current, order.location_id)
    if StaffRole.MANAGER not in current.roles:
        raise OrderDomainError("Manager access is required for refunds.", status_code=403)
    key = _idempotency_key(idempotency_key)
    order = _lock_order(db, order)
    existing_key = db.scalar(select(Refund).where(Refund.idempotency_key == key))
    if existing_key:
        if existing_key.order_id != order.id:
            raise OrderDomainError("Idempotency-Key was already used for another refund.", status_code=409)
        return existing_key, True
    existing = db.scalar(
        select(Refund).where(
            Refund.order_id == order.id, Refund.status == RefundStatus.SUCCESSFUL
        )
    )
    if existing:
        return existing, True
    payment = _successful_payment(db, order.id)
    if not payment or order.status != OrderStatus.PAID:
        raise OrderDomainError("Only a paid order can be refunded.", status_code=409)
    now = datetime.now(UTC)
    digest = hashlib.sha256(f"refund:{order.id}:{key}".encode()).hexdigest()[:24]
    refund = Refund(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        order_id=order.id,
        payment_attempt_id=payment.id,
        manager_id=current.staff_id,
        amount=_money(payment.amount),
        currency=payment.currency,
        reason=reason.strip(),
        status=RefundStatus.SUCCESSFUL,
        reference=f"refund-{digest}",
        idempotency_key=key,
        completed_at=now,
    )
    db.add(refund)
    db.flush()
    add_audit(
        db,
        order=order,
        event_type="ORDER_PAYMENT_REFUNDED",
        actor_id=current.staff_id,
        reason=reason,
        before={"refund": None},
        after={
            "refund_id": refund.id,
            "payment_attempt_id": payment.id,
            "amount": refund.amount,
            "currency": refund.currency,
            "status": refund.status,
        },
        request_id=key,
    )
    _stage_payment_event(db, order, payment)
    stage_order_changed(db, order, change="refunded")
    return refund, False


def payment_payload(attempt: PaymentAttempt, *, duplicate: bool = False) -> dict:
    return {
        "id": attempt.id,
        "order_id": attempt.order_id,
        "method": attempt.method,
        "amount": attempt.amount,
        "currency": attempt.currency,
        "status": attempt.status,
        "reference": attempt.reference,
        "provider_code": attempt.provider_code,
        "failure_reason": attempt.failure_reason,
        "created_at": _as_utc(attempt.created_at),
        "completed_at": _as_utc(attempt.completed_at),
        "duplicate": duplicate,
    }


def refund_payload(refund: Refund, *, duplicate: bool = False) -> dict:
    return {
        "id": refund.id,
        "order_id": refund.order_id,
        "payment_attempt_id": refund.payment_attempt_id,
        "amount": refund.amount,
        "currency": refund.currency,
        "reason": refund.reason,
        "status": refund.status,
        "reference": refund.reference,
        "created_at": _as_utc(refund.created_at),
        "completed_at": _as_utc(refund.completed_at),
        "duplicate": duplicate,
    }
