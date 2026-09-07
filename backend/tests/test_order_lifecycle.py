from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from datetime import UTC, datetime
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

from app.auth import current_staff_from_account  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.events import public_order_channel  # noqa: E402
from app.models import (  # noqa: E402
    AuditEvent,
    Customer,
    DiningTable,
    InvitationStatus,
    LineStatus,
    Location,
    MenuCategory,
    MenuItem,
    MenuItemType,
    ModifierGroup,
    ModifierOption,
    Order,
    OrderLine,
    OrderStatus,
    QueueDestination,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    TableVisit,
    Tenant,
)  # noqa: E402
from app.order_service import OrderDomainError, claim_line, order_version  # noqa: E402
from app.qr_service import issue_table_qr  # noqa: E402
from app.realtime import InMemoryEventBus  # noqa: E402
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.prep import create_prep_router  # noqa: E402
from app.routers.public_orders import create_public_orders_router  # noqa: E402
from app.routers.staff_orders import create_staff_orders_router  # noqa: E402


PASSWORD = "CorrectHorse!2026"


@pytest.fixture()
def harness() -> Generator[dict, None, None]:
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionFactory() as db:
        tenant = Tenant(name="Order Tenant", retention_days=90)
        foreign_tenant = Tenant(name="Foreign Tenant")
        db.add_all([tenant, foreign_tenant])
        db.flush()
        location = Location(
            tenant_id=tenant.id,
            name="Lagos Room",
            address="1 Marina",
            vat_rate=Decimal("0.075"),
            service_charge_rate=Decimal("0.025"),
        )
        foreign_location = Location(
            tenant_id=foreign_tenant.id, name="Other Room", address="2 Marina"
        )
        db.add_all([location, foreign_location])
        db.flush()
        table1 = DiningTable(
            tenant_id=tenant.id, location_id=location.id, label="T1", capacity=4
        )
        table2 = DiningTable(
            tenant_id=tenant.id, location_id=location.id, label="T2", capacity=6
        )
        db.add_all([table1, table2])
        category = MenuCategory(
            tenant_id=tenant.id, location_id=location.id, name="Menu"
        )
        db.add(category)
        db.flush()
        food = MenuItem(
            tenant_id=tenant.id,
            location_id=location.id,
            category_id=category.id,
            category=category.name,
            name="Jollof",
            description="Rice",
            item_type=MenuItemType.FOOD,
            queue_destination=QueueDestination.KITCHEN,
            base_price=Decimal("100.00"),
        )
        drink = MenuItem(
            tenant_id=tenant.id,
            location_id=location.id,
            category_id=category.id,
            category=category.name,
            name="Zobo",
            description="Drink",
            item_type=MenuItemType.DRINK,
            queue_destination=QueueDestination.BAR,
            base_price=Decimal("50.00"),
        )
        db.add_all([food, drink])
        db.flush()
        group = ModifierGroup(
            tenant_id=tenant.id,
            location_id=location.id,
            menu_item_id=food.id,
            name="Protein",
            minimum_selections=1,
            maximum_selections=1,
        )
        db.add(group)
        db.flush()
        option = ModifierOption(
            tenant_id=tenant.id,
            location_id=location.id,
            menu_item_id=food.id,
            group_id=group.id,
            name="Chicken",
            price_delta=Decimal("10.00"),
        )
        db.add(option)
        db.flush()

        password_hash = hash_password(PASSWORD)

        def staff(
            name: str,
            email: str,
            staff_tenant: Tenant,
            role: StaffRole,
            staff_location: Location,
        ) -> StaffAccount:
            account = StaffAccount(
                tenant_id=staff_tenant.id,
                name=name,
                email=email,
                password_hash=password_hash,
                invitation_status=InvitationStatus.ACCEPTED,
                accepted_at=datetime.now(UTC),
            )
            db.add(account)
            db.flush()
            db.add(
                StaffRoleAssignment(
                    tenant_id=staff_tenant.id, staff_id=account.id, role=role
                )
            )
            db.add(
                StaffLocationAssignment(
                    tenant_id=staff_tenant.id,
                    location_id=staff_location.id,
                    staff_id=account.id,
                )
            )
            return account

        manager = staff("Manager", "manager@orders.example.com", tenant, StaffRole.MANAGER, location)
        waiter1 = staff("Waiter One", "waiter1@orders.example.com", tenant, StaffRole.WAITER, location)
        waiter2 = staff("Waiter Two", "waiter2@orders.example.com", tenant, StaffRole.WAITER, location)
        chef = staff("Chef", "chef@orders.example.com", tenant, StaffRole.CHEF, location)
        bartender = staff("Bartender", "bar@orders.example.com", tenant, StaffRole.BARTENDER, location)
        foreign_manager = staff(
            "Foreign Manager",
            "manager@foreign.example.com",
            foreign_tenant,
            StaffRole.MANAGER,
            foreign_location,
        )
        db.flush()
        qr = issue_table_qr(
            db,
            table=table1,
            location=location,
            secret=get_settings().session_signing_secret,
            generated_by_id=manager.id,
        )
        qr_token = qr.raw_token
        db.commit()
        ids = {
            "tenant": tenant.id,
            "foreign_tenant": foreign_tenant.id,
            "location": location.id,
            "foreign_location": foreign_location.id,
            "table1": table1.id,
            "table2": table2.id,
            "food": food.id,
            "drink": drink.id,
            "option": option.id,
            "manager": manager.id,
            "waiter1": waiter1.id,
            "waiter2": waiter2.id,
            "chef": chef.id,
            "bartender": bartender.id,
            "foreign_manager": foreign_manager.id,
        }

    bus = InMemoryEventBus()
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(create_public_orders_router(bus))
    app.include_router(create_staff_orders_router(bus))
    app.include_router(create_prep_router(bus))

    def override_db() -> Generator[Session, None, None]:
        with SessionFactory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield {
            "client": client,
            "Session": SessionFactory,
            "ids": ids,
            "qr": qr_token,
            "bus": bus,
        }
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/staff/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def submit(
    harness: dict,
    *,
    phone: str = "0800 000 0001",
    lines: list[dict] | None = None,
) -> dict:
    response = harness["client"].post(
        f"/api/v1/public/tables/{harness['qr']}/orders",
        json={
            "customer": {
                "name": "Ada Diner",
                "phone": phone,
                "email": "ada@example.com",
            },
            "service_mode": "DINE_IN",
            "lines": lines
            or [
                {
                    "menu_item_id": harness["ids"]["food"],
                    "quantity": 2,
                    "modifier_option_ids": [harness["ids"]["option"]],
                    "special_instruction": "Less salt",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def public_headers(order: dict) -> dict[str, str]:
    return {"X-Order-Access-Token": order["access_token"]}


def test_public_orders_require_customer_snapshot_prices_token_and_never_merge(harness: dict) -> None:
    first = submit(harness)
    second = submit(harness, phone="+234-800-000-0001")
    assert first["id"] != second["id"]
    assert first["status"] == "SUBMITTED"
    assert first["recommended_wait_minutes"] == 5
    assert first["wait_time_suggestions"] == [5, 10, 15, 30, 45]
    assert first["subtotal_amount"] == "220.00"
    assert first["vat_amount"] == "16.50"
    assert first["service_charge_amount"] == "5.50"
    assert first["total_amount"] == "242.00"
    assert first["lines"][0]["base_unit_price"] == "100.00"
    assert first["lines"][0]["modifiers"] == [
        {"id": harness["ids"]["option"], "name": "Chicken", "price_delta": "10.00"}
    ]
    assert "status" not in first["lines"][0]
    client = harness["client"]
    route = f"/api/v1/public/orders/{first['id']}"
    assert client.get(route).status_code == 404
    assert client.get(route, headers={"X-Order-Access-Token": "guess"}).status_code == 404
    assert client.get(route, headers=public_headers(first)).status_code == 200
    assert client.post(
        f"{route}/realtime-grant", headers=public_headers(first)
    ).status_code == 200
    with harness["Session"]() as db:
        assert len(list(db.scalars(select(Customer)))) == 1
        rows = list(db.scalars(select(Order).order_by(Order.created_at)))
        assert len(rows) == 2
        assert rows[0].table_id == rows[1].table_id == harness["ids"]["table1"]
        assert rows[0].public_access_token_hash != first["access_token"]
        assert first["access_token"] not in rows[0].public_access_token_hash
        assert rows[0].customer_tenant_record_id is not None
    events = asyncio.run(harness["bus"].replay(public_order_channel(first["id"]), 0))
    assert any(event.payload["change"] == "submitted" for event in events)


def test_optional_preparer_assignment_and_delayed_state(harness: dict) -> None:
    client = harness["client"]
    order = submit(harness, lines=[
        {"menu_item_id": harness["ids"]["food"], "quantity": 1, "modifier_option_ids": [harness["ids"]["option"]]},
        {"menu_item_id": harness["ids"]["drink"], "quantity": 1},
    ])
    login(client, "waiter1@orders.example.com")
    preparers = client.get("/api/v1/staff/preparers").json()
    assert {row["id"] for row in preparers} == {harness["ids"]["chef"], harness["ids"]["bartender"]}
    accepted = client.post(
        f"/api/v1/staff/orders/{order['id']}/accept",
        json={"expected_version": order["version"], "estimated_wait_minutes": 30, "chef_id": harness["ids"]["chef"], "bartender_id": harness["ids"]["bartender"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert {line["status"] for line in accepted.json()["lines"]} == {"CLAIMED"}
    delayed = client.post(
        f"/api/v1/staff/orders/{order['id']}/delay",
        json={"expected_version": accepted.json()["version"], "reason": "Kitchen equipment recovery", "estimated_wait_minutes": 45},
    )
    assert delayed.status_code == 200, delayed.text
    assert delayed.json()["status"] == "DELAYED"
    assert delayed.json()["delay_reason"] == "Kitchen equipment recovery"
    public = client.get(f"/api/v1/public/orders/{order['id']}", headers=public_headers(order))
    assert public.json()["diner_status"] == "DELAYED"
    login(client, "chef@orders.example.com")
    assert [row["queue_destination"] for row in client.get("/api/v1/staff/prep").json()] == ["KITCHEN"]
    login(client, "bar@orders.example.com")
    assert [row["queue_destination"] for row in client.get("/api/v1/staff/prep").json()] == ["BAR"]


def test_diner_preacceptance_switch_cancel_stale_conflict_and_postacceptance_denial(harness: dict) -> None:
    client = harness["client"]
    order = submit(harness)
    switched = client.patch(
        f"/api/v1/public/orders/{order['id']}/service-mode",
        headers=public_headers(order),
        json={"service_mode": "TAKEAWAY", "expected_version": order["version"]},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["table_id"] is None
    stale = client.post(
        f"/api/v1/public/orders/{order['id']}/cancel",
        headers=public_headers(order),
        json={"reason": "Changed mind", "expected_version": order["version"]},
    )
    assert stale.status_code == 412
    cancelled = client.post(
        f"/api/v1/public/orders/{order['id']}/cancel",
        headers=public_headers(order),
        json={"reason": "Changed mind", "expected_version": switched.json()["version"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancellation_reason"] == "Changed mind"

    accepted = submit(harness)
    login(client, "manager@orders.example.com")
    accepted_staff = client.post(
        f"/api/v1/staff/orders/{accepted['id']}/accept",
        json={
            "waiter_id": harness["ids"]["waiter1"],
            "estimated_wait_minutes": 15,
            "expected_version": accepted["version"],
        },
    )
    assert accepted_staff.status_code == 200, accepted_staff.text
    assert client.patch(
        f"/api/v1/public/orders/{accepted['id']}/service-mode",
        headers=public_headers(accepted),
        json={
            "service_mode": "TAKEAWAY",
            "expected_version": accepted_staff.json()["version"],
        },
    ).status_code == 409
    assert client.post(
        f"/api/v1/public/orders/{accepted['id']}/cancel",
        headers=public_headers(accepted),
        json={"reason": "Too late", "expected_version": accepted_staff.json()["version"]},
    ).status_code == 409


def test_ownership_reassignment_transfer_amendment_claim_lock_manual_and_audit(harness: dict) -> None:
    client = harness["client"]
    order = submit(harness)
    login(client, "waiter1@orders.example.com")
    accepted = client.post(
        f"/api/v1/staff/orders/{order['id']}/accept",
        json={"estimated_wait_minutes": 10, "expected_version": order["version"]},
    ).json()
    amended = client.patch(
        f"/api/v1/staff/orders/{order['id']}/lines/{accepted['lines'][0]['id']}",
        json={
            "quantity": 3,
            "modifier_option_ids": [harness["ids"]["option"]],
            "special_instruction": "No pepper",
            "reason": "Diner request",
            "expected_version": accepted["version"],
        },
    )
    assert amended.status_code == 200, amended.text
    assert amended.json()["total_amount"] == "363.00"
    changed_wait = client.post(
        f"/api/v1/staff/orders/{order['id']}/wait-time",
        headers={"Idempotency-Key": "wait-once"},
        json={
            "minutes": 27,
            "source": "MANUAL",
            "expected_version": amended.json()["version"],
        },
    )
    assert changed_wait.status_code == 200, changed_wait.text
    replayed = client.post(
        f"/api/v1/staff/orders/{order['id']}/wait-time",
        headers={"Idempotency-Key": "wait-once"},
        json={
            "minutes": 27,
            "source": "MANUAL",
            "expected_version": amended.json()["version"],
        },
    )
    assert replayed.status_code == 200

    login(client, "manager@orders.example.com")
    reassigned = client.post(
        f"/api/v1/staff/orders/{order['id']}/reassign",
        json={
            "waiter_id": harness["ids"]["waiter2"],
            "reason": "Shift handover",
            "expected_version": changed_wait.json()["version"],
        },
    )
    assert reassigned.status_code == 200, reassigned.text
    login(client, "waiter1@orders.example.com")
    assert client.post(
        f"/api/v1/staff/orders/{order['id']}/transfer",
        json={
            "table_id": harness["ids"]["table2"],
            "reason": "Guests moved",
            "expected_version": reassigned.json()["version"],
        },
    ).status_code == 403
    login(client, "waiter2@orders.example.com")
    transferred = client.post(
        f"/api/v1/staff/orders/{order['id']}/transfer",
        json={
            "table_id": harness["ids"]["table2"],
            "reason": "Guests moved",
            "expected_version": reassigned.json()["version"],
        },
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["table_id"] == harness["ids"]["table2"]
    public = client.get(
        f"/api/v1/public/orders/{order['id']}", headers=public_headers(order)
    ).json()
    assert "T2" in public["transfer_notice"]

    login(client, "chef@orders.example.com")
    claimed = client.post(
        f"/api/v1/staff/lines/{transferred.json()['lines'][0]['id']}/claim",
        json={"expected_version": transferred.json()["version"]},
    )
    assert claimed.status_code == 200, claimed.text
    login(client, "waiter2@orders.example.com")
    assert client.patch(
        f"/api/v1/staff/orders/{order['id']}/lines/{claimed.json()['line_id']}",
        json={
            "quantity": 2,
            "reason": "Too late",
            "expected_version": claimed.json()["order_version"],
        },
    ).status_code == 409
    login(client, "manager@orders.example.com")
    cancelled_line = client.patch(
        f"/api/v1/staff/orders/{order['id']}/lines/{claimed.json()['line_id']}",
        json={
            "cancel_line": True,
            "reason": "Manager resolved with kitchen",
            "expected_version": claimed.json()["order_version"],
        },
    )
    assert cancelled_line.status_code == 200, cancelled_line.text
    assert cancelled_line.json()["status"] == "CANCELLED"

    manual = client.post(
        "/api/v1/staff/orders/manual",
        json={
            "location_id": harness["ids"]["location"],
            "customer": {"name": "Walk In", "phone": "08000000002"},
            "service_mode": "DINE_IN",
            "table_id": harness["ids"]["table1"],
            "waiter_id": harness["ids"]["waiter1"],
            "estimated_wait_minutes": 30,
            "lines": [
                {"menu_item_id": harness["ids"]["drink"], "quantity": 1}
            ],
        },
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["source"] == "MANUAL"
    assert manual.json()["status"] == "PREPARING"
    timeline = client.get(f"/api/v1/staff/orders/{order['id']}/timeline")
    assert timeline.status_code == 200, timeline.text
    types = {row["event_type"] for row in timeline.json()}
    assert {
        "ORDER_ACCEPTED",
        "ORDER_LINE_AMENDED",
        "ORDER_WAIT_TIME_CHANGED",
        "ORDER_REASSIGNED",
        "ORDER_TRANSFERRED",
        "PREPARATION_LINE_CLAIMED",
        "ORDER_LINE_CANCELLED",
    }.issubset(types)


def test_role_specific_prep_aggregate_ready_serve_cancel_and_isolation(harness: dict) -> None:
    client = harness["client"]
    order = submit(
        harness,
        lines=[
            {
                "menu_item_id": harness["ids"]["food"],
                "quantity": 1,
                "modifier_option_ids": [harness["ids"]["option"]],
            },
            {"menu_item_id": harness["ids"]["drink"], "quantity": 1},
        ],
    )
    login(client, "waiter1@orders.example.com")
    accepted = client.post(
        f"/api/v1/staff/orders/{order['id']}/accept",
        json={"estimated_wait_minutes": 15, "expected_version": order["version"]},
    ).json()
    food_line = next(row for row in accepted["lines"] if row["queue_destination"] == "KITCHEN")
    drink_line = next(row for row in accepted["lines"] if row["queue_destination"] == "BAR")

    login(client, "chef@orders.example.com")
    prep = client.get("/api/v1/staff/prep").json()
    assert {row["line_id"] for row in prep} == {food_line["id"]}
    assert all("customer" not in row and "phone" not in str(row) for row in prep)
    assert client.post(
        f"/api/v1/staff/lines/{drink_line['id']}/claim",
        json={"expected_version": accepted["version"]},
    ).status_code == 403
    food_claimed = client.post(
        f"/api/v1/staff/lines/{food_line['id']}/claim",
        json={"expected_version": accepted["version"]},
    ).json()

    login(client, "bar@orders.example.com")
    current = client.get(f"/api/v1/staff/orders/{order['id']}")
    assert current.status_code == 403
    # Prep view carries the safe current aggregate version without exposing contact.
    bar_line = client.get("/api/v1/staff/prep").json()[0]
    drink_claimed = client.post(
        f"/api/v1/staff/lines/{drink_line['id']}/claim",
        json={"expected_version": bar_line["order_version"]},
    )
    assert drink_claimed.status_code == 200, drink_claimed.text

    login(client, "chef@orders.example.com")
    chef_line = client.get("/api/v1/staff/prep").json()[0]
    food_ready = client.post(
        f"/api/v1/staff/lines/{food_line['id']}/ready",
        headers={"Idempotency-Key": "food-ready-once"},
        json={"expected_version": chef_line["order_version"]},
    )
    assert food_ready.status_code == 200, food_ready.text
    with harness["Session"]() as db:
        assert db.get(Order, order["id"]).status == OrderStatus.PREPARING

    login(client, "bar@orders.example.com")
    bar_line = client.get("/api/v1/staff/prep").json()[0]
    drink_ready = client.post(
        f"/api/v1/staff/lines/{drink_line['id']}/ready",
        json={"expected_version": bar_line["order_version"]},
    )
    assert drink_ready.status_code == 200, drink_ready.text
    with harness["Session"]() as db:
        assert db.get(Order, order["id"]).status == OrderStatus.READY

    login(client, "waiter1@orders.example.com")
    detail = client.get(f"/api/v1/staff/orders/{order['id']}").json()
    served = client.post(
        f"/api/v1/staff/orders/{order['id']}/serve",
        json={"expected_version": detail["version"]},
    )
    assert served.status_code == 200, served.text
    assert served.json()["status"] == "SERVED"

    login(client, "manager@foreign.example.com")
    assert client.get(f"/api/v1/staff/orders/{order['id']}").status_code == 404
    assert client.get(f"/api/v1/staff/orders/{order['id']}/timeline").status_code == 404

    cancellation = submit(harness)
    login(client, "waiter1@orders.example.com")
    accepted_cancel = client.post(
        f"/api/v1/staff/orders/{cancellation['id']}/accept",
        json={"estimated_wait_minutes": 10, "expected_version": cancellation["version"]},
    ).json()
    cancelled = client.post(
        f"/api/v1/staff/orders/{cancellation['id']}/cancel",
        json={"reason": "Diner requested waiter help", "expected_version": accepted_cancel["version"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancellation_reason"] == "Diner requested waiter help"

    # A public order snapshot remains a bearer-capability response: an order
    # ID alone, or another valid order's token, cannot enumerate this reason.
    public_route = f"/api/v1/public/orders/{cancellation['id']}"
    assert client.get(public_route).status_code == 404
    assert client.get(
        public_route,
        headers={"X-Order-Access-Token": order["access_token"]},
    ).status_code == 404
    public_snapshot = client.get(
        public_route, headers=public_headers(cancellation)
    )
    assert public_snapshot.status_code == 200, public_snapshot.text
    assert public_snapshot.json()["cancellation_reason"] == "Diner requested waiter help"
    assert "owner_id" not in public_snapshot.json()
    assert "customer" not in public_snapshot.json()
    with harness["Session"]() as db:
        row = db.get(Order, cancellation["id"])
        assert row.cancellation_reason == "Diner requested waiter help"
        assert all(line.status == LineStatus.CANCELLED for line in row.lines)


def test_atomic_claim_rejects_second_preparer_loaded_before_first_commit(harness: dict) -> None:
    order_data = submit(harness)
    client = harness["client"]
    login(client, "waiter1@orders.example.com")
    accepted = client.post(
        f"/api/v1/staff/orders/{order_data['id']}/accept",
        json={"estimated_wait_minutes": 10, "expected_version": order_data["version"]},
    ).json()
    line_id = accepted["lines"][0]["id"]
    SessionFactory = harness["Session"]
    first = SessionFactory()
    second = SessionFactory()
    try:
        first_order = first.get(Order, order_data["id"])
        first_line = first.get(OrderLine, line_id)
        second_order = second.get(Order, order_data["id"])
        second_line = second.get(OrderLine, line_id)
        first_chef = current_staff_from_account(first, first.get(StaffAccount, harness["ids"]["chef"]))
        second_chef = current_staff_from_account(second, second.get(StaffAccount, harness["ids"]["chef"]))
        version = order_version(first_order)
        assert order_version(second_order) == version
        claim_line(
            first,
            order=first_order,
            line=first_line,
            current=first_chef,
            expected_version=version,
        )
        first.commit()
        with pytest.raises(OrderDomainError) as captured:
            claim_line(
                second,
                order=second_order,
                line=second_line,
                current=second_chef,
                expected_version=version,
            )
        assert captured.value.status_code == 409
        second.rollback()
    finally:
        first.close()
        second.close()
    with SessionFactory() as db:
        line = db.get(OrderLine, line_id)
        assert line.status == LineStatus.CLAIMED
        assert line.claimed_by_id == harness["ids"]["chef"]
        claims = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.subject_id == line_id,
                    AuditEvent.event_type == "PREPARATION_LINE_CLAIMED",
                )
            )
        )
        assert len(claims) == 1
