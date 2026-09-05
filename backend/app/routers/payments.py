"""Secure public and staff payment, refund, and receipt routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentStaff
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import require_roles
from app.events import EventBus, commit_and_publish
from app.models import (
    Order,
    PaymentAttempt,
    PaymentMethod,
    Receipt,
    ReceiptDeliveryStatus,
    Refund,
    StaffRole,
)
from app.order_service import (
    OrderDomainError,
    public_order_or_404,
    raise_order_http,
    scoped_order,
)
from app.payment_schemas import (
    CashPaymentIn,
    OnlinePaymentIn,
    PaymentAttemptOut,
    ReceiptOut,
    RefundIn,
    RefundOut,
    StaffPaymentDetailsOut,
)
from app.payment_service import (
    DeterministicMockPaymentProvider,
    PaymentProvider,
    create_online_payment,
    payment_payload,
    record_cash_payment,
    refund_full_payment,
    refund_payload,
)
from app.realtime import RedisEventBus
from app.receipt_service import (
    ensure_receipt,
    mark_delivery_enqueue_failed,
    receipt_payload,
    refresh_receipt_after_refund,
)
from app.tasks import send_receipt_email


ReceiptDispatcher = Callable[[str, str], object]


def _public_token(request: Request, header_token: str | None) -> str | None:
    return header_token or request.query_params.get("access_token")


def _default_receipt_dispatcher(order_id: str, email: str) -> object:
    return send_receipt_email.send(order_id, email)


def create_payments_router(
    event_bus: EventBus | None = None,
    *,
    provider: PaymentProvider | None = None,
    receipt_dispatcher: ReceiptDispatcher | None = None,
) -> APIRouter:
    settings = get_settings()
    bus = event_bus or RedisEventBus(
        settings.redis_url, history_limit=settings.event_history_limit
    )
    adapter = provider or DeterministicMockPaymentProvider()
    dispatch = receipt_dispatcher or _default_receipt_dispatcher
    router = APIRouter(tags=["payments and receipts"])

    async def _commit_payment_and_queue(
        db: Session, order: Order, *, issue_receipt: bool
    ) -> None:
        receipt = None
        created = False
        if issue_receipt:
            receipt, created = ensure_receipt(db, order)
        await commit_and_publish(db, bus)
        if (
            receipt
            and created
            and receipt.delivery_status == ReceiptDeliveryStatus.PENDING
            and receipt.email_to
        ):
            try:
                dispatch(order.id, receipt.email_to)
            except Exception as error:  # Payment remains committed; delivery can be retried.
                mark_delivery_enqueue_failed(db, receipt, error)

    @router.post(
        "/api/v1/public/orders/{order_id}/payments",
        response_model=PaymentAttemptOut,
    )
    async def pay_online(
        order_id: str,
        payload: OnlinePaymentIn,
        request: Request,
        access_header: str | None = Header(default=None, alias="X-Order-Access-Token"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        db: Session = Depends(get_db),
    ) -> dict:
        try:
            order = public_order_or_404(
                db, order_id, _public_token(request, access_header)
            )
            attempt, duplicate = create_online_payment(
                db,
                order=order,
                method=PaymentMethod(payload.method),
                amount=payload.amount,
                currency=payload.currency,
                scenario=payload.mock_scenario,
                idempotency_key=idempotency_key,
                provider=adapter,
            )
            await _commit_payment_and_queue(
                db, order, issue_receipt=attempt.status.value == "SUCCESSFUL"
            )
            return payment_payload(attempt, duplicate=duplicate)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.get(
        "/api/v1/staff/orders/{order_id}/payment-details",
        response_model=StaffPaymentDetailsOut,
    )
    def staff_payment_details(
        order_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)
        ),
    ) -> dict:
        """Return operational settlement history without exposing diner contact data.

        ``scoped_order`` is deliberately used before every follow-up query: a
        guessed order ID outside the active staff location returns the same 404
        as an absent order.  Waiters can record cash for an owned order, but
        cannot inspect failed attempts, refunds, or receipt delivery details.
        """
        try:
            order = scoped_order(db, order_id, current)
        except OrderDomainError as error:
            raise_order_http(error)

        attempts = list(
            db.scalars(
                select(PaymentAttempt)
                .where(
                    PaymentAttempt.tenant_id == order.tenant_id,
                    PaymentAttempt.location_id == order.location_id,
                    PaymentAttempt.order_id == order.id,
                )
                .order_by(PaymentAttempt.created_at.asc(), PaymentAttempt.id.asc())
            )
        )
        refunds = list(
            db.scalars(
                select(Refund)
                .where(
                    Refund.tenant_id == order.tenant_id,
                    Refund.location_id == order.location_id,
                    Refund.order_id == order.id,
                )
                .order_by(Refund.created_at.asc(), Refund.id.asc())
            )
        )
        receipt = db.scalar(
            select(Receipt).where(
                Receipt.tenant_id == order.tenant_id,
                Receipt.location_id == order.location_id,
                Receipt.order_id == order.id,
            )
        )
        return {
            "order_id": order.id,
            "payment_attempts": [payment_payload(attempt) for attempt in attempts],
            "refunds": [refund_payload(refund) for refund in refunds],
            "receipt_delivery": (
                {
                    "id": receipt.id,
                    "receipt_number": receipt.receipt_number,
                    "issued_at": receipt.issued_at,
                    "delivery_status": receipt.delivery_status,
                    "delivery_attempts": receipt.delivery_attempts,
                    "delivered_at": receipt.delivered_at,
                }
                if receipt
                else None
            ),
        }

    @router.post(
        "/api/v1/staff/orders/{order_id}/payments/cash",
        response_model=PaymentAttemptOut,
    )
    async def record_cash(
        order_id: str,
        payload: CashPaymentIn,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.WAITER, StaffRole.MANAGER)),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            attempt, duplicate = record_cash_payment(
                db,
                order=order,
                current=current,
                amount=payload.amount,
                currency=payload.currency,
                idempotency_key=idempotency_key,
            )
            await _commit_payment_and_queue(db, order, issue_receipt=True)
            return payment_payload(attempt, duplicate=duplicate)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post(
        "/api/v1/staff/orders/{order_id}/refunds",
        response_model=RefundOut,
    )
    async def refund_payment(
        order_id: str,
        payload: RefundIn,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.MANAGER)),
    ) -> dict:
        try:
            order = scoped_order(db, order_id, current)
            refund, duplicate = refund_full_payment(
                db,
                order=order,
                current=current,
                reason=payload.reason,
                idempotency_key=idempotency_key,
            )
            refresh_receipt_after_refund(db, order)
            await commit_and_publish(db, bus)
            return refund_payload(refund, duplicate=duplicate)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.get(
        "/api/v1/public/orders/{order_id}/receipt",
        response_model=ReceiptOut,
    )
    def digital_receipt(
        order_id: str,
        request: Request,
        access_header: str | None = Header(default=None, alias="X-Order-Access-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        try:
            public_order_or_404(db, order_id, _public_token(request, access_header))
        except OrderDomainError as error:
            raise_order_http(error)
        receipt = db.scalar(select(Receipt).where(Receipt.order_id == order_id))
        if receipt is None:
            raise_order_http(OrderDomainError("Receipt not found.", status_code=404))
        return receipt_payload(receipt)

    return router


router = create_payments_router()
