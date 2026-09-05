from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import select

from app.db import get_db
from app.models import (
    AuditEvent,
    DiningTable,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentMethod,
    PaymentStatus,
    Receipt,
    ReceiptDeliveryStatus,
    Refund,
    TableVisit,
)
from app.receipt_service import ReceiptDeliveryProvider, deliver_receipt_email_with_session
from app.routers.payments import create_payments_router
from test_order_lifecycle import harness, login, public_headers, submit  # noqa: F401


@pytest.fixture()
def payments_harness(harness: dict) -> Generator[dict, None, None]:
    queued: list[tuple[str, str]] = []
    harness["client"].app.include_router(
        create_payments_router(
            harness["bus"],
            receipt_dispatcher=lambda order_id, email: queued.append((order_id, email)),
        )
    )
    harness["queued_receipts"] = queued
    yield harness


def _serve(harness: dict, *, phone: str = "0800 900 0001") -> dict:
    client = harness["client"]
    order = submit(harness, phone=phone)
    login(client, "waiter1@orders.example.com")
    accepted = client.post(
        f"/api/v1/staff/orders/{order['id']}/accept",
        json={"estimated_wait_minutes": 10, "expected_version": order["version"]},
    )
    assert accepted.status_code == 200, accepted.text
    login(client, "chef@orders.example.com")
    prep = client.get("/api/v1/staff/prep").json()
    line = next(row for row in prep if row["order_id"] == order["id"])
    claimed = client.post(
        f"/api/v1/staff/lines/{line['line_id']}/claim",
        json={"expected_version": line["order_version"]},
    )
    assert claimed.status_code == 200, claimed.text
    current = next(
        row for row in client.get("/api/v1/staff/prep").json() if row["order_id"] == order["id"]
    )
    ready = client.post(
        f"/api/v1/staff/lines/{line['line_id']}/ready",
        json={"expected_version": current["order_version"]},
    )
    assert ready.status_code == 200, ready.text
    login(client, "waiter1@orders.example.com")
    detail = client.get(f"/api/v1/staff/orders/{order['id']}").json()
    served = client.post(
        f"/api/v1/staff/orders/{order['id']}/serve",
        json={"expected_version": detail["version"]},
    )
    assert served.status_code == 200, served.text
    return order


def _public_pay(harness: dict, order: dict, *, key: str, **payload):
    body = {"method": "CARD", "mock_scenario": "APPROVED", **payload}
    return harness["client"].post(
        f"/api/v1/public/orders/{order['id']}/payments",
        headers={**public_headers(order), "Idempotency-Key": key},
        json=body,
    )


def test_public_payment_requires_secure_served_order_and_never_accepts_cash(
    payments_harness: dict,
) -> None:
    h = payments_harness
    order = submit(h, phone="0800 900 0002")
    assert _public_pay(h, order, key="premature").status_code == 409
    assert h["client"].post(
        f"/api/v1/public/orders/{order['id']}/payments",
        headers={"X-Order-Access-Token": "guess", "Idempotency-Key": "guess"},
        json={"method": "CARD"},
    ).status_code == 404
    assert h["client"].post(
        f"/api/v1/public/orders/{order['id']}/payments",
        headers={**public_headers(order), "Idempotency-Key": "cash-public"},
        json={"method": "CASH"},
    ).status_code == 422
    with h["Session"]() as db:
        assert list(db.scalars(select(PaymentAttempt))) == []


def test_failed_attempts_are_persisted_retry_is_safe_and_success_is_single(
    payments_harness: dict,
) -> None:
    h = payments_harness
    order = _serve(h, phone="0800 900 0003")
    declined = _public_pay(h, order, key="decline-1", mock_scenario="DECLINED")
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "FAILED"
    duplicate_failure = _public_pay(h, order, key="decline-1", mock_scenario="APPROVED")
    assert duplicate_failure.status_code == 200
    assert duplicate_failure.json()["id"] == declined.json()["id"]
    assert duplicate_failure.json()["duplicate"] is True
    temporary = _public_pay(
        h, order, key="temporary-1", mock_scenario="TEMPORARY_FAILURE"
    )
    assert temporary.json()["provider_code"] == "TEMPORARY_FAILURE"
    paid = _public_pay(h, order, key="success-1", method="TRANSFER")
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "SUCCESSFUL"
    replay = _public_pay(h, order, key="success-1", method="TRANSFER")
    assert replay.json()["id"] == paid.json()["id"]
    after_success = _public_pay(h, order, key="success-2", method="WALLET")
    assert after_success.json()["id"] == paid.json()["id"]
    with h["Session"]() as db:
        attempts = list(
            db.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == order["id"]))
        )
        assert len(attempts) == 3
        assert sum(row.status == PaymentStatus.SUCCESSFUL for row in attempts) == 1
        persisted = db.get(Order, order["id"])
        assert persisted.status == OrderStatus.PAID
        assert persisted.paid_at is not None
        visit = db.get(TableVisit, persisted.visit_id)
        table = db.get(DiningTable, persisted.table_id)
        assert visit.closed_at is not None
        assert table.is_active is False
    assert h["queued_receipts"] == [(order["id"], "ada@example.com")]


def test_server_rejects_amount_currency_and_idempotency_payload_tampering(
    payments_harness: dict,
) -> None:
    h = payments_harness
    first = _serve(h, phone="0800 900 0004")
    assert _public_pay(h, first, key="bad-amount", amount="1.00").status_code == 409
    assert _public_pay(h, first, key="bad-currency", currency="USD").status_code == 409
    failed = _public_pay(h, first, key="shared-key", mock_scenario="DECLINED")
    assert failed.status_code == 200
    second = _serve(h, phone="0800 900 0005")
    reused = _public_pay(h, second, key="shared-key")
    assert reused.status_code == 409


def test_staff_cash_is_owner_or_manager_only_and_is_audited(payments_harness: dict) -> None:
    h = payments_harness
    client = h["client"]
    order = _serve(h, phone="0800 900 0006")
    login(client, "waiter2@orders.example.com")
    route = f"/api/v1/staff/orders/{order['id']}/payments/cash"
    denied = client.post(route, headers={"Idempotency-Key": "cash-denied"}, json={})
    assert denied.status_code == 403
    login(client, "waiter1@orders.example.com")
    paid = client.post(
        route,
        headers={"Idempotency-Key": "cash-success"},
        json={"amount": "242.00", "currency": "NGN"},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["method"] == PaymentMethod.CASH
    replay = client.post(
        route, headers={"Idempotency-Key": "cash-success"}, json={}
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == paid.json()["id"]
    with h["Session"]() as db:
        attempt = db.get(PaymentAttempt, paid.json()["id"])
        assert attempt.recorded_by_id == h["ids"]["waiter1"]
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.subject_id == order["id"],
                AuditEvent.event_type == "ORDER_PAYMENT_RECORDED",
            )
        )
        assert audit.actor_id == h["ids"]["waiter1"]


def test_manager_full_refund_is_reasoned_idempotent_and_updates_receipt(
    payments_harness: dict,
) -> None:
    h = payments_harness
    client = h["client"]
    order = _serve(h, phone="0800 900 0007")
    paid = _public_pay(h, order, key="refund-payment")
    assert paid.status_code == 200
    route = f"/api/v1/staff/orders/{order['id']}/refunds"
    login(client, "waiter1@orders.example.com")
    assert client.post(
        route, headers={"Idempotency-Key": "refund-denied"}, json={"reason": "Diner request"}
    ).status_code == 403
    login(client, "manager@orders.example.com")
    refunded = client.post(
        route,
        headers={"Idempotency-Key": "refund-success"},
        json={"reason": "Duplicate service charge resolution"},
    )
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["amount"] == paid.json()["amount"]
    replay = client.post(
        route,
        headers={"Idempotency-Key": "refund-other-key"},
        json={"reason": "Must not refund twice"},
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == refunded.json()["id"]
    assert replay.json()["duplicate"] is True
    receipt = client.get(
        f"/api/v1/public/orders/{order['id']}/receipt", headers=public_headers(order)
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["refunded"] is True
    assert "Duplicate service charge resolution" in receipt.json()["html"]
    with h["Session"]() as db:
        assert len(list(db.scalars(select(Refund).where(Refund.order_id == order["id"])))) == 1
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.subject_id == order["id"],
                AuditEvent.event_type == "ORDER_PAYMENT_REFUNDED",
            )
        )
        assert event.actor_id == h["ids"]["manager"]
        assert event.detail == "Duplicate service charge resolution"


def test_payment_detail_is_manager_only_location_scoped_and_hides_diner_contact(
    payments_harness: dict,
) -> None:
    h = payments_harness
    client = h["client"]
    order = _serve(h, phone="0800 900 0009")
    assert _public_pay(h, order, key="detail-declined", mock_scenario="DECLINED").status_code == 200
    paid = _public_pay(h, order, key="detail-paid", method="TRANSFER")
    assert paid.status_code == 200, paid.text
    detail_route = f"/api/v1/staff/orders/{order['id']}/payment-details"

    login(client, "waiter1@orders.example.com")
    assert client.get(detail_route).status_code == 403

    # A manager from another tenant/location must not be able to distinguish
    # this valid order ID from an unknown one.
    login(client, "manager@foreign.example.com")
    assert client.get(detail_route).status_code == 404

    login(client, "manager@orders.example.com")
    response = client.get(detail_route)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_id"] == order["id"]
    assert [row["status"] for row in body["payment_attempts"]] == ["FAILED", "SUCCESSFUL"]
    assert body["payment_attempts"][0]["failure_reason"]
    assert body["payment_attempts"][1]["reference"] == paid.json()["reference"]
    assert body["refunds"] == []
    assert body["receipt_delivery"]["delivery_status"] == "PENDING"
    assert "email_to" not in str(body)
    assert "ada@example.com" not in str(body)

    refunded = client.post(
        f"/api/v1/staff/orders/{order['id']}/refunds",
        headers={"Idempotency-Key": "detail-refund"},
        json={"reason": "Diner was charged twice"},
    )
    assert refunded.status_code == 200, refunded.text
    after_refund = client.get(detail_route).json()
    assert after_refund["refunds"] == [
        {
            **refunded.json(),
            "duplicate": False,
        }
    ]


def test_receipt_is_token_protected_complete_and_delivery_state_is_retry_safe(
    payments_harness: dict,
) -> None:
    h = payments_harness
    order = _serve(h, phone="0800 900 0008")
    assert _public_pay(h, order, key="receipt-payment").status_code == 200
    route = f"/api/v1/public/orders/{order['id']}/receipt"
    assert h["client"].get(route).status_code == 404
    assert h["client"].get(
        route, headers={"X-Order-Access-Token": "guess"}
    ).status_code == 404
    response = h["client"].get(route, headers=public_headers(order))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["payload"]["restaurant"]["tenant_name"] == "Order Tenant"
    assert data["payload"]["restaurant"]["location_name"] == "Lagos Room"
    assert data["payload"]["order"]["vat_amount"] == "16.50"
    assert data["payload"]["order"]["service_charge_amount"] == "5.50"
    assert data["payload"]["order"]["lines"][0]["modifiers"][0]["name"] == "Chicken"
    assert data["payload"]["payment"]["reference"].startswith("mock-")
    assert "Jollof" in data["html"] and "NGN 242.00" in data["html"]

    class FlakyProvider(ReceiptDeliveryProvider):
        calls = 0

        def deliver(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("mail offline")
            return {"provider_id": "mail-ok"}

    provider = FlakyProvider()
    with h["Session"]() as db:
        with pytest.raises(ConnectionError):
            deliver_receipt_email_with_session(
                db,
                order_id=order["id"],
                email="ada@example.com",
                idempotency_key="receipt-v1",
                provider=provider,
            )
        failed = db.scalar(select(Receipt).where(Receipt.order_id == order["id"]))
        assert failed.delivery_status == ReceiptDeliveryStatus.FAILED
        assert failed.delivery_attempts == 1
        sent = deliver_receipt_email_with_session(
            db,
            order_id=order["id"],
            email="ada@example.com",
            idempotency_key="receipt-v1",
            provider=provider,
        )
        assert sent["status"] == "sent"
        duplicate = deliver_receipt_email_with_session(
            db,
            order_id=order["id"],
            email="ada@example.com",
            idempotency_key="receipt-v1",
            provider=provider,
        )
        assert duplicate["status"] == "duplicate"
        receipt = db.scalar(select(Receipt).where(Receipt.order_id == order["id"]))
        assert receipt.delivery_status == ReceiptDeliveryStatus.SENT
        assert receipt.delivery_attempts == 2
        assert receipt.delivered_at is not None
