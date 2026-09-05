from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["CHOWLY_ENVIRONMENT"] = "test"
os.environ["CHOWLY_SESSION_SIGNING_SECRET"] = "report-test-session-secret-with-32-characters"

from app.auth import CurrentStaff  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.dependencies import get_current_staff  # noqa: E402
from app.models import (  # noqa: E402
    AuditEvent,
    Complaint,
    ComplaintStatus,
    Customer,
    CustomerTenantRecord,
    InvitationStatus,
    ItemRating,
    LineStatus,
    Location,
    MenuCategory,
    MenuItem,
    MenuItemType,
    Order,
    OrderLine,
    OrderRating,
    OrderSource,
    OrderStatus,
    PaymentAttempt,
    PaymentMethod,
    PaymentStatus,
    QueueDestination,
    Refund,
    RefundStatus,
    ServiceMode,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    Tenant,
)  # noqa: E402
from app.routers.reports import router as reports_router  # noqa: E402


REPORT_DAY = "2026-08-31"
T0 = datetime(2026, 8, 30, 23, 30, tzinfo=UTC)  # 00:30 on report day in Lagos


def _staff(
    db: Session, tenant: Tenant, location: Location, name: str, role: StaffRole
) -> StaffAccount:
    account = StaffAccount(
        tenant_id=tenant.id,
        name=name,
        email=f"{name.lower()}-{tenant.id}@example.com",
        invitation_status=InvitationStatus.ACCEPTED,
        accepted_at=T0,
    )
    db.add(account)
    db.flush()
    db.add_all(
        [
            StaffRoleAssignment(tenant_id=tenant.id, staff_id=account.id, role=role),
            StaffLocationAssignment(
                tenant_id=tenant.id, location_id=location.id, staff_id=account.id
            ),
        ]
    )
    return account


def _principal(
    account: StaffAccount, tenant: Tenant, location: Location, role: StaffRole
) -> CurrentStaff:
    return CurrentStaff(
        account=account,
        tenant_id=tenant.id,
        roles=frozenset({role}),
        location_ids=frozenset({location.id}),
        active_location_id=location.id,
        locations=(location,),
    )


def _order(
    db: Session,
    *,
    tenant: Tenant,
    location: Location,
    customer: Customer,
    record: CustomerTenantRecord,
    item: MenuItem,
    created_at: datetime,
    status: OrderStatus,
    amount: Decimal,
    quantity: int = 1,
    accepted_at: datetime | None = None,
    ready_at: datetime | None = None,
    served_at: datetime | None = None,
    paid_at: datetime | None = None,
    cancelled_at: datetime | None = None,
    cancellation_reason: str | None = None,
) -> Order:
    order = Order(
        tenant_id=tenant.id,
        location_id=location.id,
        customer_id=customer.id,
        customer_tenant_record_id=record.id,
        source=OrderSource.QR,
        service_mode=ServiceMode.TAKEAWAY,
        status=status,
        currency="NGN",
        subtotal_amount=amount,
        total_amount=amount,
        accepted_at=accepted_at,
        ready_at=ready_at,
        served_at=served_at,
        paid_at=paid_at,
        cancelled_at=cancelled_at,
        cancellation_reason=cancellation_reason,
        created_at=created_at,
        updated_at=cancelled_at or paid_at or served_at or created_at,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderLine(
            tenant_id=tenant.id,
            location_id=location.id,
            order_id=order.id,
            menu_item_id=item.id,
            quantity=quantity,
            item_name_snapshot=item.name,
            queue_destination=QueueDestination.KITCHEN,
            unit_price=amount / quantity,
            subtotal_amount=amount,
            total_amount=amount,
            status=LineStatus.CANCELLED if status == OrderStatus.CANCELLED else LineStatus.READY,
            created_at=created_at,
            updated_at=cancelled_at or served_at or created_at,
            cancelled_at=cancelled_at if status == OrderStatus.CANCELLED else None,
        )
    )
    return order


@pytest.fixture()
def harness() -> Generator[dict, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionFactory() as db:
        tenant = Tenant(name="Report Tenant")
        other_tenant = Tenant(name="Foreign Tenant")
        db.add_all([tenant, other_tenant])
        db.flush()
        location = Location(
            tenant_id=tenant.id,
            name="Lagos",
            address="1 Marina",
            timezone="Africa/Lagos",
            currency="NGN",
        )
        sibling = Location(
            tenant_id=tenant.id,
            name="Abuja",
            address="2 Central",
            timezone="Africa/Lagos",
            currency="NGN",
        )
        foreign = Location(
            tenant_id=other_tenant.id,
            name="Foreign",
            address="Elsewhere",
            timezone="UTC",
            currency="NGN",
        )
        db.add_all([location, sibling, foreign])
        db.flush()
        manager = _staff(db, tenant, location, "Manager", StaffRole.MANAGER)
        owner = _staff(db, tenant, location, "Owner", StaffRole.TENANT_OWNER)
        waiter = _staff(db, tenant, location, "Waiter", StaffRole.WAITER)
        foreign_manager = _staff(
            db, other_tenant, foreign, "ForeignManager", StaffRole.MANAGER
        )
        category = MenuCategory(
            tenant_id=tenant.id, location_id=location.id, name="Mains"
        )
        foreign_category = MenuCategory(
            tenant_id=other_tenant.id, location_id=foreign.id, name="Mains"
        )
        db.add_all([category, foreign_category])
        db.flush()
        item = MenuItem(
            tenant_id=tenant.id,
            location_id=location.id,
            category_id=category.id,
            category="Mains",
            name="Jollof",
            description="",
            item_type=MenuItemType.FOOD,
            queue_destination=QueueDestination.KITCHEN,
            base_price=Decimal("500.00"),
        )
        foreign_item = MenuItem(
            tenant_id=other_tenant.id,
            location_id=foreign.id,
            category_id=foreign_category.id,
            category="Mains",
            name="Foreign item",
            description="",
            item_type=MenuItemType.FOOD,
            queue_destination=QueueDestination.KITCHEN,
            base_price=Decimal("9000.00"),
        )
        db.add_all([item, foreign_item])
        customer = Customer(name="Ada", phone="+2348000000001")
        foreign_customer = Customer(name="Eve", phone="+2348000000099")
        db.add_all([customer, foreign_customer])
        db.flush()
        record = CustomerTenantRecord(
            tenant_id=tenant.id,
            customer_id=customer.id,
            name_snapshot="Ada",
            phone_snapshot=customer.phone,
        )
        foreign_record = CustomerTenantRecord(
            tenant_id=other_tenant.id,
            customer_id=foreign_customer.id,
            name_snapshot="Eve",
            phone_snapshot=foreign_customer.phone,
        )
        db.add_all([record, foreign_record])
        db.flush()

        paid_one = _order(
            db,
            tenant=tenant,
            location=location,
            customer=customer,
            record=record,
            item=item,
            created_at=T0,
            status=OrderStatus.PAID,
            amount=Decimal("1000.00"),
            quantity=2,
            accepted_at=T0 + timedelta(minutes=10),
            ready_at=T0 + timedelta(minutes=40),
            served_at=T0 + timedelta(minutes=50),
            paid_at=T0 + timedelta(minutes=55),
        )
        paid_two = _order(
            db,
            tenant=tenant,
            location=location,
            customer=customer,
            record=record,
            item=item,
            created_at=T0 + timedelta(hours=18),
            status=OrderStatus.PAID,
            amount=Decimal("500.00"),
            accepted_at=T0 + timedelta(hours=18, minutes=5),
            ready_at=T0 + timedelta(hours=18, minutes=25),
            served_at=T0 + timedelta(hours=18, minutes=30),
            paid_at=T0 + timedelta(hours=18, minutes=35),
        )
        _order(
            db,
            tenant=tenant,
            location=location,
            customer=customer,
            record=record,
            item=item,
            created_at=T0 + timedelta(hours=2),
            status=OrderStatus.SERVED,
            amount=Decimal("300.00"),
        )
        diner_cancel = _order(
            db,
            tenant=tenant,
            location=location,
            customer=customer,
            record=record,
            item=item,
            created_at=T0 + timedelta(hours=3),
            status=OrderStatus.CANCELLED,
            amount=Decimal("250.00"),
            cancelled_at=T0 + timedelta(hours=3, minutes=2),
            cancellation_reason="Duplicate",
        )
        staff_cancel = _order(
            db,
            tenant=tenant,
            location=location,
            customer=customer,
            record=record,
            item=item,
            created_at=T0 + timedelta(hours=4),
            status=OrderStatus.CANCELLED,
            amount=Decimal("200.00"),
            cancelled_at=T0 + timedelta(hours=4, minutes=5),
            cancellation_reason="Kitchen unavailable",
        )
        # This is 23:59 on August 30 in Lagos and must be excluded.
        _order(
            db,
            tenant=tenant,
            location=location,
            customer=customer,
            record=record,
            item=item,
            created_at=datetime(2026, 8, 30, 22, 59, tzinfo=UTC),
            status=OrderStatus.SERVED,
            amount=Decimal("999.00"),
        )
        foreign_order = _order(
            db,
            tenant=other_tenant,
            location=foreign,
            customer=foreign_customer,
            record=foreign_record,
            item=foreign_item,
            created_at=T0,
            status=OrderStatus.PAID,
            amount=Decimal("9000.00"),
            paid_at=T0 + timedelta(minutes=1),
        )

        success_one = PaymentAttempt(
            tenant_id=tenant.id,
            location_id=location.id,
            order_id=paid_one.id,
            method=PaymentMethod.CARD,
            amount=Decimal("1000.00"),
            currency="NGN",
            status=PaymentStatus.SUCCESSFUL,
            reference="pay-1",
            idempotency_key="pay-1",
            created_at=T0 + timedelta(minutes=55),
            completed_at=T0 + timedelta(minutes=55),
        )
        success_two = PaymentAttempt(
            tenant_id=tenant.id,
            location_id=location.id,
            order_id=paid_two.id,
            method=PaymentMethod.CASH,
            amount=Decimal("500.00"),
            currency="NGN",
            status=PaymentStatus.SUCCESSFUL,
            reference="pay-2",
            idempotency_key="pay-2",
            recorded_by_id=manager.id,
            created_at=T0 + timedelta(hours=18, minutes=35),
            completed_at=T0 + timedelta(hours=18, minutes=35),
        )
        failed = PaymentAttempt(
            tenant_id=tenant.id,
            location_id=location.id,
            order_id=paid_one.id,
            method=PaymentMethod.TRANSFER,
            amount=Decimal("1000.00"),
            currency="NGN",
            status=PaymentStatus.FAILED,
            reference="pay-failed",
            idempotency_key="pay-failed",
            failure_reason="mock failure",
            created_at=T0 + timedelta(hours=1),
            completed_at=T0 + timedelta(hours=1),
        )
        foreign_payment = PaymentAttempt(
            tenant_id=other_tenant.id,
            location_id=foreign.id,
            order_id=foreign_order.id,
            method=PaymentMethod.CARD,
            amount=Decimal("9000.00"),
            currency="NGN",
            status=PaymentStatus.SUCCESSFUL,
            reference="foreign-pay",
            idempotency_key="foreign-pay",
            created_at=T0,
            completed_at=T0,
        )
        db.add_all([success_one, success_two, failed, foreign_payment])
        db.flush()
        db.add(
            Refund(
                tenant_id=tenant.id,
                location_id=location.id,
                order_id=paid_one.id,
                payment_attempt_id=success_one.id,
                manager_id=manager.id,
                amount=Decimal("1000.00"),
                currency="NGN",
                reason="Full reversal",
                status=RefundStatus.SUCCESSFUL,
                reference="refund-1",
                idempotency_key="refund-1",
                created_at=T0 + timedelta(hours=2),
                completed_at=T0 + timedelta(hours=2),
            )
        )
        db.add_all(
            [
                AuditEvent(
                    tenant_id=tenant.id,
                    location_id=location.id,
                    actor_id=None,
                    event_type="ORDER_CANCELLED_BY_DINER",
                    subject_type="ORDER",
                    subject_id=diner_cancel.id,
                    detail="Duplicate",
                    before_data={"status": "SUBMITTED"},
                    after_data={"status": "CANCELLED"},
                    created_at=diner_cancel.cancelled_at,
                ),
                AuditEvent(
                    tenant_id=tenant.id,
                    location_id=location.id,
                    actor_id=manager.id,
                    event_type="ORDER_CANCELLED",
                    subject_type="ORDER",
                    subject_id=staff_cancel.id,
                    detail="Kitchen unavailable",
                    before_data={"status": "PREPARING"},
                    after_data={"status": "CANCELLED"},
                    created_at=staff_cancel.cancelled_at,
                ),
            ]
        )
        order_rating_one = OrderRating(
            tenant_id=tenant.id,
            location_id=location.id,
            order_id=paid_one.id,
            customer_id=customer.id,
            score=5,
            created_at=T0 + timedelta(hours=5),
        )
        order_rating_two = OrderRating(
            tenant_id=tenant.id,
            location_id=location.id,
            order_id=paid_two.id,
            customer_id=customer.id,
            score=1,
            created_at=T0 + timedelta(hours=19),
        )
        db.add_all([order_rating_one, order_rating_two])
        db.flush()
        paid_lines = {line.order_id: line for line in db.query(OrderLine).all()}
        item_rating_one = ItemRating(
            tenant_id=tenant.id,
            location_id=location.id,
            order_id=paid_one.id,
            order_line_id=paid_lines[paid_one.id].id,
            customer_id=customer.id,
            score=4,
            created_at=T0 + timedelta(hours=5),
        )
        item_rating_two = ItemRating(
            tenant_id=tenant.id,
            location_id=location.id,
            order_id=paid_two.id,
            order_line_id=paid_lines[paid_two.id].id,
            customer_id=customer.id,
            score=2,
            created_at=T0 + timedelta(hours=19),
        )
        db.add_all([item_rating_one, item_rating_two])
        db.flush()
        db.add_all(
            [
                Complaint(
                    tenant_id=tenant.id,
                    location_id=location.id,
                    order_id=paid_one.id,
                    customer_id=customer.id,
                    order_rating_id=order_rating_one.id,
                    subject="Cold food",
                    detail="Meal was cold",
                    status=ComplaintStatus.RESOLVED,
                    resolution_note="Replaced",
                    resolved_by_id=manager.id,
                    created_at=T0 + timedelta(hours=6),
                    resolved_at=T0 + timedelta(hours=10),
                ),
                Complaint(
                    tenant_id=tenant.id,
                    location_id=location.id,
                    order_id=paid_two.id,
                    customer_id=customer.id,
                    item_rating_id=item_rating_two.id,
                    subject="Slow",
                    detail="Too slow",
                    status=ComplaintStatus.OPEN,
                    created_at=T0 + timedelta(hours=20),
                ),
            ]
        )
        db.commit()
        principals = {
            "manager": _principal(manager, tenant, location, StaffRole.MANAGER),
            "owner": _principal(owner, tenant, location, StaffRole.TENANT_OWNER),
            "waiter": _principal(waiter, tenant, location, StaffRole.WAITER),
            "foreign": _principal(
                foreign_manager, other_tenant, foreign, StaffRole.MANAGER
            ),
        }
        ids = {
            "location": location.id,
            "sibling": sibling.id,
            "foreign": foreign.id,
        }

    actor = {"current": principals["manager"]}
    app = FastAPI()
    app.include_router(reports_router)

    def override_db() -> Generator[Session, None, None]:
        with SessionFactory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_staff] = lambda: actor["current"]
    with TestClient(app) as client:
        yield {
            "client": client,
            "actor": actor,
            "principals": principals,
            "ids": ids,
        }
    Base.metadata.drop_all(engine)
    engine.dispose()


def _report(client: TestClient, location_id: str, day: str = REPORT_DAY):
    return client.get(
        f"/api/v1/staff/locations/{location_id}/reports/operations",
        params={"start_date": day, "end_date": day},
    )


def test_report_has_every_metric_and_correct_financial_semantics(harness: dict) -> None:
    response = _report(harness["client"], harness["ids"]["location"])
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["currency"] == "NGN"
    assert report["date_range"]["start_utc"].startswith("2026-08-30T23:00:00")
    assert report["orders"]["total"] == 5
    assert report["orders"]["by_status"]["PAID"] == 2
    assert report["orders"]["gross_revenue"] == "1500.00"
    assert report["orders"]["refund_total"] == "1000.00"
    assert report["orders"]["net_revenue"] == "500.00"
    assert report["daily"] == [
        {
            "date": REPORT_DAY,
            "order_count": 5,
            "paid_order_count": 2,
            "gross_revenue": "1500.00",
            "refund_total": "1000.00",
            "net_revenue": "500.00",
        }
    ]
    methods = {row["method"]: row for row in report["payments"]["methods"]}
    statuses = {row["status"]: row for row in report["payments"]["statuses"]}
    assert methods["CASH"]["successful_amount"] == "500.00"
    assert methods["TRANSFER"]["successful_amount"] == "0.00"
    assert statuses["FAILED"] == {"status": "FAILED", "count": 1, "amount": "1000.00"}
    assert report["payments"]["refunds"]["successful_total"] == "1000.00"
    assert report["wait_times"]["acceptance"] == {
        "sample_count": 2,
        "average_minutes": "7.50",
    }
    assert report["wait_times"]["preparation"]["average_minutes"] == "25.00"
    assert report["wait_times"]["ready_to_serve"]["average_minutes"] == "7.50"
    assert report["wait_times"]["total"]["average_minutes"] == "40.00"
    assert report["top_items"] == [
        {"item_name": "Jollof", "quantity": 3, "paid_revenue": "1500.00"}
    ]
    assert report["cancellations"]["by_actor"] == {"DINER": 1, "MANAGER": 1}
    assert report["cancellations"]["by_stage"] == {"PREPARING": 1, "SUBMITTED": 1}
    assert report["complaints"]["by_status"]["OPEN"] == 1
    assert report["complaints"]["resolved_count"] == 1
    assert report["complaints"]["average_resolution_hours"] == "4.00"
    assert report["ratings"]["orders"]["average"] == "3.00"
    assert report["ratings"]["orders"]["distribution"] == {
        "1": 1,
        "2": 0,
        "3": 0,
        "4": 0,
        "5": 1,
    }
    assert report["ratings"]["items"]["average"] == "3.00"


def test_report_scope_roles_empty_shape_and_validation(harness: dict) -> None:
    client = harness["client"]
    actor = harness["actor"]
    principals = harness["principals"]
    ids = harness["ids"]

    actor["current"] = principals["waiter"]
    assert _report(client, ids["location"]).status_code == 403
    actor["current"] = principals["manager"]
    assert _report(client, ids["sibling"]).status_code == 404
    assert _report(client, ids["foreign"]).status_code == 404
    actor["current"] = principals["foreign"]
    foreign_report = _report(client, ids["foreign"], "2026-08-30").json()
    assert foreign_report["orders"]["gross_revenue"] == "9000.00"
    actor["current"] = principals["owner"]
    empty = _report(client, ids["location"], "2026-09-02")
    assert empty.status_code == 200
    payload = empty.json()
    assert payload["orders"]["total"] == 0
    assert payload["orders"]["gross_revenue"] == "0.00"
    assert payload["top_items"] == []
    assert payload["wait_times"]["total"] == {
        "sample_count": 0,
        "average_minutes": "0.00",
    }
    assert payload["ratings"]["items"]["distribution"] == {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 0,
        "5": 0,
    }
    invalid = client.get(
        f"/api/v1/staff/locations/{ids['location']}/reports/operations",
        params={"start_date": "2026-09-02", "end_date": "2026-08-31"},
    )
    assert invalid.status_code == 422
