from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["CHOWLY_ENVIRONMENT"] = "test"
os.environ["CHOWLY_SESSION_SIGNING_SECRET"] = "test-session-secret-with-more-than-32-characters"
os.environ["CHOWLY_REALTIME_SIGNING_SECRET"] = "test-realtime-secret-with-more-than-32-characters"

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_opaque_token, issue_staff_session  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.models import (  # noqa: E402
    AuditEvent,
    Complaint,
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
    OrderSource,
    OrderStatus,
    QueueDestination,
    ServiceMode,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    Tenant,
)
from app.retention_service import cleanup_expired_tenant_records  # noqa: E402
from app.routers.feedback import router as feedback_router  # noqa: E402
from app.routers.retention import router as retention_router  # noqa: E402


NOW = datetime.now(UTC)
PUBLIC_TOKEN = "served-order-private-link-token"
SUBMITTED_TOKEN = "submitted-order-private-link-token"


@pytest.fixture()
def harness() -> Generator[dict, None, None]:
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSession() as db:
        tenant_a = Tenant(name="Feedback Tenant A")
        tenant_b = Tenant(name="Feedback Tenant B")
        db.add_all([tenant_a, tenant_b])
        db.flush()
        location_a = Location(tenant_id=tenant_a.id, name="A Lagos", address="1 A Street")
        location_b = Location(tenant_id=tenant_b.id, name="B Lagos", address="2 B Street")
        db.add_all([location_a, location_b])
        db.flush()

        def staff(
            name: str,
            tenant: Tenant | None,
            role: StaffRole | None,
            location: Location | None,
            *,
            platform: bool = False,
        ) -> StaffAccount:
            row = StaffAccount(
                tenant_id=tenant.id if tenant else None,
                name=name,
                email=f"{name.lower().replace(' ', '-')}@example.test",
                password_hash="not-used-by-session-tests",
                invitation_status=InvitationStatus.ACCEPTED,
                accepted_at=NOW,
                is_platform_admin=platform,
            )
            db.add(row)
            db.flush()
            if tenant and role and location:
                db.add(StaffRoleAssignment(tenant_id=tenant.id, staff_id=row.id, role=role))
                db.add(StaffLocationAssignment(tenant_id=tenant.id, location_id=location.id, staff_id=row.id))
            return row

        owner = staff("Owner A", tenant_a, StaffRole.TENANT_OWNER, location_a)
        manager = staff("Manager A", tenant_a, StaffRole.MANAGER, location_a)
        waiter = staff("Waiter A", tenant_a, StaffRole.WAITER, location_a)
        chef = staff("Chef A", tenant_a, StaffRole.CHEF, location_a)
        manager_b = staff("Manager B", tenant_b, StaffRole.MANAGER, location_b)
        platform = staff("Platform Admin", None, None, None, platform=True)

        shared = Customer(name="Shared Customer", phone="+2348000001001", email="shared@example.test")
        exclusive = Customer(name="Exclusive Customer", phone="+2348000001002", email="exclusive@example.test")
        db.add_all([shared, exclusive])
        db.flush()
        record_a = CustomerTenantRecord(
            tenant_id=tenant_a.id,
            customer_id=shared.id,
            name_snapshot=shared.name,
            phone_snapshot=shared.phone,
            email=shared.email,
            first_seen_at=NOW - timedelta(days=200),
            last_seen_at=NOW - timedelta(days=150),
        )
        record_b = CustomerTenantRecord(
            tenant_id=tenant_b.id,
            customer_id=shared.id,
            name_snapshot=shared.name,
            phone_snapshot=shared.phone,
            email=shared.email,
            first_seen_at=NOW - timedelta(days=10),
            last_seen_at=NOW - timedelta(days=1),
        )
        exclusive_record = CustomerTenantRecord(
            tenant_id=tenant_a.id,
            customer_id=exclusive.id,
            name_snapshot=exclusive.name,
            phone_snapshot=exclusive.phone,
            email=exclusive.email,
            first_seen_at=NOW - timedelta(days=200),
            last_seen_at=NOW - timedelta(days=150),
        )
        db.add_all([record_a, record_b, exclusive_record])
        db.flush()

        category_a = MenuCategory(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            name="Mains",
        )
        category_b = MenuCategory(
            tenant_id=tenant_b.id,
            location_id=location_b.id,
            name="Drinks",
        )
        db.add_all([category_a, category_b])
        db.flush()
        item_a = MenuItem(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            name="Jollof rice",
            category_id=category_a.id,
            category="Mains",
            item_type=MenuItemType.FOOD,
            queue_destination=QueueDestination.KITCHEN,
            base_price=Decimal("5000.00"),
        )
        item_b = MenuItem(
            tenant_id=tenant_b.id,
            location_id=location_b.id,
            name="Chapman",
            category_id=category_b.id,
            category="Drinks",
            item_type=MenuItemType.DRINK,
            queue_destination=QueueDestination.BAR,
            base_price=Decimal("1500.00"),
        )
        db.add_all([item_a, item_b])
        db.flush()

        def order(
            *,
            tenant: Tenant,
            location: Location,
            customer: Customer,
            record: CustomerTenantRecord,
            item: MenuItem,
            token: str,
            status: OrderStatus,
            created_at: datetime = NOW,
        ) -> tuple[Order, OrderLine]:
            row = Order(
                tenant_id=tenant.id,
                location_id=location.id,
                customer_id=customer.id,
                customer_tenant_record_id=record.id,
                public_access_token_hash=hash_opaque_token(token),
                source=OrderSource.QR,
                service_mode=ServiceMode.TAKEAWAY,
                status=status,
                currency="NGN",
                subtotal_amount=Decimal("5000.00"),
                vat_amount=Decimal("375.00"),
                service_charge_amount=Decimal("0.00"),
                total_amount=Decimal("5375.00"),
                served_at=NOW if status in {OrderStatus.SERVED, OrderStatus.PAID} else None,
                paid_at=NOW if status == OrderStatus.PAID else None,
                created_at=created_at,
            )
            db.add(row)
            db.flush()
            line = OrderLine(
                tenant_id=tenant.id,
                location_id=location.id,
                order_id=row.id,
                menu_item_id=item.id,
                quantity=1,
                item_name_snapshot=item.name,
                queue_destination=QueueDestination.KITCHEN if item.item_type == MenuItemType.FOOD else QueueDestination.BAR,
                unit_price=Decimal("5000.00"),
                subtotal_amount=Decimal("5000.00"),
                vat_amount=Decimal("375.00"),
                service_charge_amount=Decimal("0.00"),
                total_amount=Decimal("5375.00"),
                status=LineStatus.READY,
            )
            db.add(line)
            db.flush()
            return row, line

        served, served_line = order(
            tenant=tenant_a,
            location=location_a,
            customer=shared,
            record=record_a,
            item=item_a,
            token=PUBLIC_TOKEN,
            status=OrderStatus.SERVED,
        )
        submitted, submitted_line = order(
            tenant=tenant_a,
            location=location_a,
            customer=shared,
            record=record_a,
            item=item_a,
            token=SUBMITTED_TOKEN,
            status=OrderStatus.SUBMITTED,
        )
        old_financial, _ = order(
            tenant=tenant_a,
            location=location_a,
            customer=exclusive,
            record=exclusive_record,
            item=item_a,
            token="old-financial-order-token",
            status=OrderStatus.PAID,
            created_at=NOW - timedelta(days=150),
        )
        other_order, _ = order(
            tenant=tenant_b,
            location=location_b,
            customer=shared,
            record=record_b,
            item=item_b,
            token="tenant-b-order-token",
            status=OrderStatus.SERVED,
        )
        db.commit()
        ids = {
            "tenant_a": tenant_a.id,
            "tenant_b": tenant_b.id,
            "location_a": location_a.id,
            "location_b": location_b.id,
            "owner": owner.id,
            "manager": manager.id,
            "waiter": waiter.id,
            "chef": chef.id,
            "manager_b": manager_b.id,
            "platform": platform.id,
            "shared_customer": shared.id,
            "exclusive_customer": exclusive.id,
            "record_a": record_a.id,
            "record_b": record_b.id,
            "exclusive_record": exclusive_record.id,
            "served": served.id,
            "served_line": served_line.id,
            "submitted": submitted.id,
            "submitted_line": submitted_line.id,
            "old_financial": old_financial.id,
            "other_order": other_order.id,
        }

    app = FastAPI()
    app.include_router(feedback_router)
    app.include_router(retention_router)

    def override_db() -> Generator[Session, None, None]:
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield {"client": client, "Session": TestingSession, "ids": ids}
    Base.metadata.drop_all(engine)
    engine.dispose()


def public_headers(token: str = PUBLIC_TOKEN) -> dict[str, str]:
    return {"X-Order-Access-Token": token}


def staff_session(client: TestClient, ids: dict, staff_key: str, tenant_key: str | None, location_key: str | None) -> None:
    settings = get_settings()
    token = issue_staff_session(
        staff_id=ids[staff_key],
        tenant_id=ids[tenant_key] if tenant_key else None,
        active_location_id=ids[location_key] if location_key else None,
        secret=settings.session_signing_secret,
        ttl=timedelta(hours=1),
    )
    client.cookies.set(settings.session_cookie_name, token, path="/api/v1")


def test_ratings_require_secure_post_service_link_validate_score_and_are_unique(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    rejected_early = client.post(
        f"/api/v1/public/orders/{ids['submitted']}/ratings/items",
        headers=public_headers(SUBMITTED_TOKEN),
        json={"order_line_id": ids["submitted_line"], "score": 5},
    )
    assert rejected_early.status_code == 409
    assert client.post(
        f"/api/v1/public/orders/{ids['served']}/ratings/order",
        headers=public_headers("wrong-token"),
        json={"score": 5},
    ).status_code == 404
    assert client.post(
        f"/api/v1/public/orders/{ids['served']}/ratings/order",
        headers=public_headers(),
        json={"score": 0},
    ).status_code == 422

    item = client.post(
        f"/api/v1/public/orders/{ids['served']}/ratings/items",
        headers=public_headers(),
        json={"order_line_id": ids["served_line"], "score": 1, "comment": "Too salty"},
    )
    assert item.status_code == 201, item.text
    assert item.json()["complaint_prompt"] is True
    assert item.json()["complaint_prompt_message"]
    with harness["Session"]() as db:
        assert db.scalar(select(Complaint.id)) is None
    duplicate_item = client.post(
        f"/api/v1/public/orders/{ids['served']}/ratings/items",
        headers=public_headers(),
        json={"order_line_id": ids["served_line"], "score": 2},
    )
    assert duplicate_item.status_code == 409

    overall = client.post(
        f"/api/v1/public/orders/{ids['served']}/ratings/order",
        headers=public_headers(),
        json={"score": 5, "comment": "Great service"},
    )
    assert overall.status_code == 201
    assert overall.json()["complaint_prompt"] is False
    assert overall.json()["complaint_prompt_message"] is None
    assert client.post(
        f"/api/v1/public/orders/{ids['served']}/ratings/order",
        headers=public_headers(),
        json={"score": 4},
    ).status_code == 409


def test_complaints_are_post_service_and_may_be_tied_to_a_specific_rated_line(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    assert client.post(
        f"/api/v1/public/orders/{ids['submitted']}/complaints",
        headers=public_headers(SUBMITTED_TOKEN),
        json={"subject": "Early", "detail": "Not served yet"},
    ).status_code == 409
    rating = client.post(
        f"/api/v1/public/orders/{ids['served']}/ratings/items",
        headers=public_headers(),
        json={"order_line_id": ids["served_line"], "score": 2},
    )
    item_rating_id = rating.json()["id"]
    complaint = client.post(
        f"/api/v1/public/orders/{ids['served']}/complaints",
        headers=public_headers(),
        json={"subject": "Meal issue", "detail": "The rice was cold", "item_rating_id": item_rating_id},
    )
    assert complaint.status_code == 201, complaint.text
    assert complaint.json()["order_line_id"] == ids["served_line"]
    assert complaint.json()["status"] == "OPEN"
    assert client.post(
        f"/api/v1/public/orders/{ids['served']}/complaints",
        headers=public_headers(),
        json={"subject": "Wrong link", "detail": "Foreign rating", "item_rating_id": "not-a-rating"},
    ).status_code == 404


def test_delayed_order_allows_immediate_rating_and_complaint(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    with harness["Session"]() as db:
        order = db.get(Order, ids["submitted"])
        order.status = OrderStatus.DELAYED
        order.delay_reason = "Longer than expected"
        order.delayed_at = NOW
        db.commit()
    rating = client.post(
        f"/api/v1/public/orders/{ids['submitted']}/ratings/order",
        headers=public_headers(SUBMITTED_TOKEN),
        json={"score": 2, "comment": "The wait is too long"},
    )
    assert rating.status_code == 201, rating.text
    complaint = client.post(
        f"/api/v1/public/orders/{ids['submitted']}/complaints",
        headers=public_headers(SUBMITTED_TOKEN),
        json={"subject": "Delayed order", "detail": "Please provide an update", "order_rating_id": rating.json()["id"]},
    )
    assert complaint.status_code == 201, complaint.text


def test_only_assigned_manager_can_see_and_resolve_complaints_with_audit(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    created = client.post(
        f"/api/v1/public/orders/{ids['served']}/complaints",
        headers=public_headers(),
        json={"subject": "Service issue", "detail": "Please contact me"},
    )
    complaint_id = created.json()["id"]
    route = f"/api/v1/staff/locations/{ids['location_a']}/complaints"

    for role_key in ("waiter", "chef", "owner"):
        staff_session(client, ids, role_key, "tenant_a", "location_a")
        assert client.get(route).status_code == 403
    staff_session(client, ids, "manager_b", "tenant_b", "location_b")
    assert client.get(route).status_code == 404

    staff_session(client, ids, "manager", "tenant_a", "location_a")
    visible = client.get(route)
    assert visible.status_code == 200
    assert visible.json()["complaints"][0]["detail"] == "Please contact me"
    acknowledged = client.post(f"{route}/{complaint_id}/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "IN_REVIEW"
    resolved = client.post(
        f"{route}/{complaint_id}/resolve",
        json={"resolution_note": "Spoke to the diner and replaced the meal", "disposition": "RESOLVED"},
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "RESOLVED"
    assert body["resolved_by_id"] == ids["manager"]
    assert body["resolved_at"]
    assert client.post(
        f"{route}/{complaint_id}/resolve",
        json={"resolution_note": "Repeat"},
    ).status_code == 409
    with harness["Session"]() as db:
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.subject_id == complaint_id)
                .order_by(AuditEvent.created_at)
            )
        )
        assert [event.event_type for event in events] == [
            "COMPLAINT_ACKNOWLEDGED",
            "COMPLAINT_RESOLVED",
        ]
        assert all(event.actor_id == ids["manager"] for event in events)
        assert events[-1].after_data["resolution_note"] == "Spoke to the diner and replaced the meal"


def test_retention_defaults_direct_configuration_and_platform_approval(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    staff_session(client, ids, "owner", "tenant_a", "location_a")
    initial = client.get("/api/v1/staff/tenant/retention")
    assert initial.status_code == 200
    assert initial.json()["effective_days"] == 90
    direct = client.put("/api/v1/staff/tenant/retention", json={"days": 120})
    assert direct.status_code == 200
    assert direct.json()["state"] == "ACTIVE"
    pending = client.put("/api/v1/staff/tenant/retention", json={"days": 121})
    assert pending.status_code == 200
    assert pending.json()["effective_days"] == 120
    assert pending.json()["pending_requested_days"] == 121
    assert pending.json()["state"] == "PENDING_PLATFORM_APPROVAL"
    assert client.put("/api/v1/staff/tenant/retention", json={"days": 0}).status_code == 422
    with harness["Session"]() as db:
        assert db.get(Tenant, ids["tenant_a"]).retention_days == 120

    staff_session(client, ids, "manager", "tenant_a", "location_a")
    assert client.get("/api/v1/staff/tenant/retention").status_code == 403
    staff_session(client, ids, "platform", None, None)
    approved = client.post(f"/api/v1/platform/tenants/{ids['tenant_a']}/retention/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["effective_days"] == 121
    assert approved.json()["state"] == "APPROVED_EXTENSION"
    assert approved.json()["extension_approved_by"] == ids["platform"]


def test_cleanup_is_idempotent_tenant_isolated_and_preserves_financial_aggregates(harness: dict) -> None:
    ids = harness["ids"]
    SessionFactory = harness["Session"]
    with SessionFactory() as db:
        order_before = db.get(Order, ids["old_financial"])
        financial_before = (order_before.status, order_before.total_amount, order_before.currency)
        result = cleanup_expired_tenant_records(
            db,
            tenant_id=ids["tenant_a"],
            cutoff=NOW - timedelta(days=90),
            now=NOW,
        )
        assert result.tenant_records_anonymized == 2
        assert result.global_customers_anonymized == 1

    with SessionFactory() as db:
        record_a = db.get(CustomerTenantRecord, ids["record_a"])
        record_b = db.get(CustomerTenantRecord, ids["record_b"])
        exclusive_record = db.get(CustomerTenantRecord, ids["exclusive_record"])
        shared = db.get(Customer, ids["shared_customer"])
        exclusive = db.get(Customer, ids["exclusive_customer"])
        assert record_a.purged_at and record_a.email is None and record_a.phone_snapshot.startswith("purged-")
        assert exclusive_record.purged_at and exclusive_record.email is None
        assert record_b.purged_at is None
        assert record_b.phone_snapshot == "+2348000001001"
        assert shared.phone == "+2348000001001"
        assert exclusive.phone.startswith("purged-")
        order_after = db.get(Order, ids["old_financial"])
        assert (order_after.status, order_after.total_amount, order_after.currency) == financial_before
        assert db.scalar(select(Order.id).where(Order.id == ids["other_order"]))
        second = cleanup_expired_tenant_records(
            db,
            tenant_id=ids["tenant_a"],
            cutoff=NOW - timedelta(days=90),
            now=NOW,
        )
        assert second.tenant_records_anonymized == 0
        assert second.global_customers_anonymized == 0
