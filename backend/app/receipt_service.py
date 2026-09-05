"""Immutable receipt snapshots and durable email-delivery state."""

from __future__ import annotations

import hashlib
import html
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal
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
    CustomerTenantRecord,
    Location,
    Order,
    PaymentAttempt,
    PaymentStatus,
    Receipt,
    ReceiptDeliveryStatus,
    Refund,
    RefundStatus,
    StaffRole,
    Tenant,
)


TEMPLATE_PATH = Path(__file__).with_name("templates") / "receipt.html"


class ReceiptDeliveryProvider(Protocol):
    def deliver(
        self,
        *,
        recipient: str,
        subject: str,
        html_body: str,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class ConsoleReceiptDeliveryProvider:
    """Development adapter; intentionally performs no real external delivery."""

    def deliver(
        self,
        *,
        recipient: str,
        subject: str,
        html_body: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        digest = hashlib.sha256(f"{recipient}:{idempotency_key}".encode()).hexdigest()[:20]
        return {"provider": "console", "provider_id": f"mail-{digest}"}


def _decimal(value: Decimal) -> str:
    return f"{Decimal(value):.2f}"


def _successful_payment(db: Session, order_id: str) -> PaymentAttempt:
    payment = db.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.order_id == order_id,
            PaymentAttempt.status == PaymentStatus.SUCCESSFUL,
        )
    )
    if payment is None:
        raise ValueError("A successful payment is required before issuing a receipt.")
    return payment


def build_receipt_snapshot(db: Session, order: Order) -> dict[str, Any]:
    payment = _successful_payment(db, order.id)
    refund = db.scalar(
        select(Refund).where(
            Refund.order_id == order.id, Refund.status == RefundStatus.SUCCESSFUL
        )
    )
    location = db.scalar(
        select(Location).where(
            Location.id == order.location_id, Location.tenant_id == order.tenant_id
        )
    )
    tenant = db.get(Tenant, order.tenant_id)
    if location is None or tenant is None:
        raise ValueError("Receipt restaurant identity is unavailable.")
    lines = []
    for line in order.lines:
        lines.append(
            {
                "id": line.id,
                "name": line.item_name_snapshot,
                "quantity": line.quantity,
                "unit_price": _decimal(line.unit_price),
                "modifiers": list(line.selected_modifiers or []),
                "special_instruction": line.special_instruction,
                "subtotal_amount": _decimal(line.subtotal_amount),
                "vat_amount": _decimal(line.vat_amount),
                "service_charge_amount": _decimal(line.service_charge_amount),
                "total_amount": _decimal(line.total_amount),
            }
        )
    return {
        "restaurant": {
            "tenant_name": tenant.name,
            "location_name": location.name,
            "address": location.address,
        },
        "order": {
            "id": order.id,
            "service_mode": order.service_mode.value,
            "table_id": order.table_id,
            "served_at": order.served_at.isoformat() if order.served_at else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "currency": order.currency,
            "subtotal_amount": _decimal(order.subtotal_amount),
            "vat_rate": str(order.vat_rate_snapshot),
            "vat_amount": _decimal(order.vat_amount),
            "service_charge_rate": str(order.service_charge_rate_snapshot),
            "service_charge_amount": _decimal(order.service_charge_amount),
            "total_amount": _decimal(order.total_amount),
            "lines": lines,
        },
        "payment": {
            "method": payment.method.value,
            "reference": payment.reference,
            "amount": _decimal(payment.amount),
            "currency": payment.currency,
            "completed_at": payment.completed_at.isoformat() if payment.completed_at else None,
        },
        "refund": {
            "reference": refund.reference,
            "amount": _decimal(refund.amount),
            "currency": refund.currency,
            "reason": refund.reason,
            "completed_at": refund.completed_at.isoformat() if refund.completed_at else None,
        }
        if refund
        else None,
    }


def _email_for_order(db: Session, order: Order) -> str | None:
    if not order.customer_tenant_record_id:
        return None
    record = db.scalar(
        select(CustomerTenantRecord).where(
            CustomerTenantRecord.id == order.customer_tenant_record_id,
            CustomerTenantRecord.tenant_id == order.tenant_id,
            CustomerTenantRecord.purged_at.is_(None),
        )
    )
    return record.email.strip().lower() if record and record.email else None


def _stage_receipt_event(db: Session, order: Order, receipt: Receipt, *, change: str) -> None:
    draft = EventDraft(
        type=EventType.RECEIPT_CHANGED,
        scope=EventScope(
            tenant_id=order.tenant_id,
            location_id=order.location_id,
            order_id=order.id,
        ),
        resource=EventResource(kind=ResourceKind.RECEIPT, id=receipt.id),
        payload={
            "order_id": order.id,
            "change": change,
            "delivery_status": receipt.delivery_status.value,
        },
    )
    for role in (StaffRole.MANAGER, StaffRole.WAITER):
        stage_domain_event(
            db,
            staff_channel(order.tenant_id, order.location_id, role.value),
            draft,
        )
    stage_domain_event(db, public_order_channel(order.id), draft)


def ensure_receipt(db: Session, order: Order) -> tuple[Receipt, bool]:
    order = db.scalar(
        select(Order).options(selectinload(Order.lines)).where(Order.id == order.id)
    ) or order
    receipt = db.scalar(select(Receipt).where(Receipt.order_id == order.id))
    snapshot = build_receipt_snapshot(db, order)
    if receipt:
        receipt.payload_snapshot = snapshot
        return receipt, False
    email_to = _email_for_order(db, order)
    digest = hashlib.sha256(f"{order.tenant_id}:{order.id}".encode()).hexdigest()[:16].upper()
    receipt = Receipt(
        tenant_id=order.tenant_id,
        location_id=order.location_id,
        order_id=order.id,
        receipt_number=f"CHW-{digest}",
        payload_snapshot=snapshot,
        email_to=email_to,
        delivery_status=(
            ReceiptDeliveryStatus.PENDING
            if email_to
            else ReceiptDeliveryStatus.NOT_REQUESTED
        ),
    )
    db.add(receipt)
    db.flush()
    _stage_receipt_event(db, order, receipt, change="issued")
    return receipt, True


def refresh_receipt_after_refund(db: Session, order: Order) -> Receipt:
    receipt, created = ensure_receipt(db, order)
    if not created:
        _stage_receipt_event(db, order, receipt, change="refunded")
    return receipt


def render_receipt_html(receipt: Receipt) -> str:
    payload = receipt.payload_snapshot
    restaurant = payload["restaurant"]
    order = payload["order"]
    payment = payload["payment"]
    rows = []
    for line in order["lines"]:
        modifier_text = ", ".join(
            f"{item['name']} (+{item['price_delta']})" for item in line.get("modifiers", [])
        ) or "None"
        rows.append(
            "<tr>"
            f"<td>{html.escape(line['name'])}<small>{html.escape(modifier_text)}</small></td>"
            f"<td>{line['quantity']}</td><td>{html.escape(order['currency'])} {line['total_amount']}</td>"
            "</tr>"
        )
    refund = payload.get("refund")
    refund_block = (
        f"<p class=\"refund\">Refunded {html.escape(refund['currency'])} "
        f"{refund['amount']} — {html.escape(refund['reason'])}</p>"
        if refund
        else ""
    )
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    values = {
        "tenant_name": html.escape(restaurant["tenant_name"]),
        "location_name": html.escape(restaurant["location_name"]),
        "address": html.escape(restaurant["address"]),
        "receipt_number": html.escape(receipt.receipt_number),
        "order_id": html.escape(order["id"]),
        "issued_at": receipt.issued_at.isoformat(),
        "line_rows": "".join(rows),
        "currency": html.escape(order["currency"]),
        "subtotal": order["subtotal_amount"],
        "vat": order["vat_amount"],
        "service_charge": order["service_charge_amount"],
        "total": order["total_amount"],
        "payment_method": html.escape(payment["method"]),
        "payment_reference": html.escape(payment["reference"]),
        "refund_block": refund_block,
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def receipt_payload(receipt: Receipt) -> dict[str, Any]:
    return {
        "id": receipt.id,
        "receipt_number": receipt.receipt_number,
        "order_id": receipt.order_id,
        "issued_at": receipt.issued_at,
        "delivery_status": receipt.delivery_status,
        "delivery_attempts": receipt.delivery_attempts,
        "refunded": receipt.payload_snapshot.get("refund") is not None,
        "payload": receipt.payload_snapshot,
        "html": render_receipt_html(receipt),
    }


def mark_delivery_enqueue_failed(db: Session, receipt: Receipt, error: Exception) -> None:
    receipt.delivery_status = ReceiptDeliveryStatus.FAILED
    receipt.delivery_error = f"{type(error).__name__}: {error}"[:1000]
    db.commit()


def deliver_receipt_email(
    *,
    order_id: str,
    email: str,
    idempotency_key: str,
    provider: ReceiptDeliveryProvider | None = None,
) -> dict[str, Any]:
    with SessionLocal() as db:
        return deliver_receipt_email_with_session(
            db,
            order_id=order_id,
            email=email,
            idempotency_key=idempotency_key,
            provider=provider,
        )


def deliver_receipt_email_with_session(
    db: Session,
    *,
    order_id: str,
    email: str,
    idempotency_key: str,
    provider: ReceiptDeliveryProvider | None = None,
) -> dict[str, Any]:
    """Execute one delivery against an injected session (used by worker and tests)."""

    adapter = provider or ConsoleReceiptDeliveryProvider()
    receipt = db.scalar(select(Receipt).where(Receipt.order_id == order_id))
    if receipt is None or not receipt.email_to or receipt.email_to != email.strip().lower():
        raise ValueError("Receipt delivery target was not found.")
    if receipt.delivery_status == ReceiptDeliveryStatus.SENT:
        return {"status": "duplicate", "receipt_id": receipt.id}
    receipt.delivery_attempts += 1
    receipt.delivery_status = ReceiptDeliveryStatus.PENDING
    receipt.delivery_error = None
    db.commit()
    try:
        result = adapter.deliver(
            recipient=receipt.email_to,
            subject=f"Chowly receipt {receipt.receipt_number}",
            html_body=render_receipt_html(receipt),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        receipt.delivery_status = ReceiptDeliveryStatus.FAILED
        receipt.delivery_error = f"{type(error).__name__}: {error}"[:1000]
        db.commit()
        raise
    receipt.delivery_status = ReceiptDeliveryStatus.SENT
    receipt.delivered_at = datetime.now(UTC)
    receipt.delivery_error = None
    db.commit()
    return {"status": "sent", "receipt_id": receipt.id, **result}
