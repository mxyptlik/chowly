from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, configure_mappers, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["CHOWLY_ENVIRONMENT"] = "test"
os.environ["CHOWLY_SESSION_SIGNING_SECRET"] = "test-session-secret-with-more-than-32-characters"
os.environ["CHOWLY_REALTIME_SIGNING_SECRET"] = "test-realtime-secret-with-more-than-32-characters"

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.events import staff_channel  # noqa: E402
from app.location_service import location_is_currently_open  # noqa: E402
from app.models import (  # noqa: E402
    AuditEvent,
    Customer,
    CustomerTenantRecord,
    DiningTable,
    InvitationStatus,
    Location,
    MenuCategory,
    MenuItem,
    MenuItemType,
    ModifierGroup,
    ModifierOption,
    OperatingHour,
    Order,
    OrderStatus,
    QueueDestination,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    TableQrToken,
    TableVisit,
    Tenant,
)  # noqa: E402
from app.qr_service import (  # noqa: E402
    InvalidTableQr,
    calculate_table_activity,
    issue_table_qr,
    ensure_daily_table_qrs,
    resolve_table_qr,
)  # noqa: E402
from app.realtime import InMemoryEventBus  # noqa: E402
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.locations import router as locations_router  # noqa: E402
from app.routers.menu import create_menu_router  # noqa: E402
from app.routers.tables import create_tables_router  # noqa: E402


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
        tenant_a = Tenant(name="Tenant A")
        tenant_b = Tenant(name="Tenant B")
        db.add_all([tenant_a, tenant_b])
        db.flush()
        location_a = Location(
            tenant_id=tenant_a.id,
            name="Lagos Dining Room",
            address="1 Marina Road",
            vat_rate=Decimal("0.075"),
            service_charge_rate=Decimal("0.025"),
            timezone="Africa/Lagos",
        )
        location_b = Location(
            tenant_id=tenant_b.id,
            name="Foreign Location",
            address="2 Other Road",
        )
        db.add_all([location_a, location_b])
        db.flush()
        category = MenuCategory(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            name="Mains",
            sort_order=10,
        )
        db.add(category)
        db.flush()
        item = MenuItem(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            category_id=category.id,
            category=category.name,
            name="Jollof",
            description="Smoky rice",
            item_type=MenuItemType.FOOD,
            queue_destination=QueueDestination.KITCHEN,
            base_price=Decimal("100.05"),
        )
        db.add(item)
        drink = MenuItem(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            category_id=category.id,
            category=category.name,
            name="Zobo",
            description="Hibiscus drink",
            item_type=MenuItemType.DRINK,
            queue_destination=QueueDestination.BAR,
            base_price=Decimal("75.00"),
        )
        db.add(drink)
        db.flush()
        group = ModifierGroup(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            menu_item_id=item.id,
            name="Protein",
            minimum_selections=1,
            maximum_selections=1,
        )
        db.add(group)
        db.flush()
        option = ModifierOption(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            menu_item_id=item.id,
            group_id=group.id,
            name="Chicken",
            price_delta=Decimal("0.05"),
        )
        db.add(option)
        table = DiningTable(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            label="T1",
            capacity=4,
        )
        db.add(table)
        customer = Customer(name="Ada", phone="+2348000000001")
        db.add(customer)
        db.flush()
        customer_record = CustomerTenantRecord(
            tenant_id=tenant_a.id,
            customer_id=customer.id,
            name_snapshot=customer.name,
            phone_snapshot=customer.phone,
        )
        db.add(customer_record)

        password_hash = hash_password(PASSWORD)

        def add_staff(
            name: str,
            email: str,
            tenant: Tenant,
            role: StaffRole,
            locations: list[Location],
        ) -> StaffAccount:
            account = StaffAccount(
                tenant_id=tenant.id,
                name=name,
                email=email,
                password_hash=password_hash,
                invitation_status=InvitationStatus.ACCEPTED,
                accepted_at=datetime.now(UTC),
            )
            db.add(account)
            db.flush()
            db.add(StaffRoleAssignment(tenant_id=tenant.id, staff_id=account.id, role=role))
            for assigned in locations:
                db.add(
                    StaffLocationAssignment(
                        tenant_id=tenant.id,
                        location_id=assigned.id,
                        staff_id=account.id,
                    )
                )
            return account

        owner = add_staff(
            "Owner", "owner@tenant-a.example.com", tenant_a, StaffRole.TENANT_OWNER, [location_a]
        )
        manager = add_staff(
            "Manager", "manager@tenant-a.example.com", tenant_a, StaffRole.MANAGER, [location_a]
        )
        waiter = add_staff(
            "Waiter", "waiter@tenant-a.example.com", tenant_a, StaffRole.WAITER, [location_a]
        )
        chef = add_staff(
            "Chef", "chef@tenant-a.example.com", tenant_a, StaffRole.CHEF, [location_a]
        )
        bartender = add_staff(
            "Bartender", "bartender@tenant-a.example.com", tenant_a, StaffRole.BARTENDER, [location_a]
        )
        other_manager = add_staff(
            "Other", "manager@tenant-b.example.com", tenant_b, StaffRole.MANAGER, [location_b]
        )
        db.commit()
        ids = {
            "tenant_a": tenant_a.id,
            "tenant_b": tenant_b.id,
            "location_a": location_a.id,
            "location_b": location_b.id,
            "category": category.id,
            "item": item.id,
            "drink": drink.id,
            "group": group.id,
            "option": option.id,
            "table": table.id,
            "customer": customer.id,
            "customer_record": customer_record.id,
            "owner": owner.id,
            "manager": manager.id,
            "waiter": waiter.id,
            "chef": chef.id,
            "bartender": bartender.id,
            "other_manager": other_manager.id,
        }

    bus = InMemoryEventBus()
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(locations_router)
    app.include_router(create_menu_router(bus))
    app.include_router(create_tables_router(bus))

    def override_db() -> Generator[Session, None, None]:
        with SessionFactory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield {"client": client, "Session": SessionFactory, "ids": ids, "bus": bus}
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/staff/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def test_cursor_collection_endpoints_filter_and_preserve_legacy_lists(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    login(client, "manager@tenant-a.example.com")
    base = f"/api/v1/staff/locations/{ids['location_a']}"
    assert isinstance(client.get(f"{base}/tables").json(), list)
    tables = client.get(f"{base}/tables/list?limit=1&enabled=true")
    assert tables.status_code == 200, tables.text
    assert len(tables.json()["items"]) == 1
    assert tables.json()["has_more"] is False
    drinks = client.get(f"{base}/menu/items/list?item_type=DRINK&available=true&limit=1")
    assert drinks.status_code == 200, drinks.text
    assert [item["name"] for item in drinks.json()["items"]] == ["Zobo"]
    categories = client.get(f"{base}/menu/categories/list?limit=1")
    assert categories.status_code == 200, categories.text
    assert categories.json()["items"][0]["id"] == ids["category"]


def test_daily_qr_ensure_is_idempotent(harness: dict) -> None:
    with harness["Session"]() as db:
        first = ensure_daily_table_qrs(db, secret="test-secret")
        db.commit()
        second = ensure_daily_table_qrs(db, secret="test-secret")
        assert first == (1, 0)
        assert second == (0, 1)


def test_manual_order_catalog_returns_human_readable_location_scoped_choices(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    login(client, "waiter@tenant-a.example.com")
    route = f"/api/v1/staff/locations/{ids['location_a']}/manual-order-catalog"
    response = client.get(route)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["location_id"] == ids["location_a"]
    assert payload["tables"] == [
        {"id": ids["table"], "label": "T1", "capacity": 4, "is_active": False}
    ]
    assert {item["name"] for item in payload["menu"]} == {"Jollof", "Zobo"}
    jollof = next(item for item in payload["menu"] if item["name"] == "Jollof")
    assert jollof["modifier_groups"][0]["options"][0]["name"] == "Chicken"

    login(client, "manager@tenant-b.example.com")
    assert client.get(route).status_code == 404


def test_location_crud_is_owner_only_assigned_and_hours_are_exposed(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    login(client, "manager@tenant-a.example.com")
    assert client.get("/api/v1/staff/locations").status_code == 200
    assert client.get(f"/api/v1/staff/locations/{ids['location_b']}").status_code == 404
    assert client.post(
        "/api/v1/staff/locations",
        json={"name": "Manager Branch", "address": "No access"},
    ).status_code == 403
    assert client.patch(
        f"/api/v1/staff/locations/{ids['location_a']}", json={"name": "No"}
    ).status_code == 403

    login(client, "owner@tenant-a.example.com")
    created = client.post(
        "/api/v1/staff/locations",
        json={
            "name": "Abuja Dining Room",
            "address": "3 Central Area",
            "timezone": "Africa/Lagos",
            "vat_rate": "0.075",
            "service_charge_rate": "0",
        },
    )
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]
    assert client.get(f"/api/v1/staff/locations/{new_id}").status_code == 200
    renamed = client.patch(
        f"/api/v1/staff/locations/{new_id}", json={"name": "Abuja Central"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Abuja Central"
    hours = client.put(
        f"/api/v1/staff/locations/{ids['location_a']}/operating-hours",
        json=[
            {"weekday": 0, "opens_at": "09:00", "closes_at": "23:00"},
            {"weekday": 1, "is_closed": True},
        ],
    )
    assert hours.status_code == 200, hours.text
    assert len(hours.json()["operating_hours"]) == 2
    assert client.put(
        f"/api/v1/staff/locations/{ids['location_a']}/operating-hours",
        json=[
            {"weekday": 0, "opens_at": "09:00", "closes_at": "17:00"},
            {"weekday": 0, "opens_at": "18:00", "closes_at": "20:00"},
        ],
    ).status_code == 422
    assert client.delete(f"/api/v1/staff/locations/{new_id}").status_code == 204


def test_operating_hours_support_closed_and_overnight_timezone_windows() -> None:
    monday = OperatingHour(weekday=0, opens_at=time(18), closes_at=time(2), is_closed=False)
    location = Location(
        tenant_id="tenant",
        name="Night Room",
        address="Night Street",
        timezone="Africa/Lagos",
        is_open=True,
        is_active=True,
        operating_hours=[monday],
    )
    # Monday 19:00 local and Tuesday 01:00 local are both in the overnight window.
    assert location_is_currently_open(location, now=datetime(2026, 8, 31, 18, tzinfo=UTC))
    assert location_is_currently_open(location, now=datetime(2026, 9, 1, 0, tzinfo=UTC))
    assert not location_is_currently_open(location, now=datetime(2026, 9, 1, 2, tzinfo=UTC))
    location.is_open = False
    assert not location_is_currently_open(location, now=datetime(2026, 8, 31, 18, tzinfo=UTC))


def test_menu_modifier_validation_sold_out_pricing_and_realtime(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    bus = harness["bus"]
    login(client, "manager@tenant-a.example.com")
    items = client.get(f"/api/v1/staff/locations/{ids['location_a']}/menu/items")
    assert items.status_code == 200, items.text
    assert items.json()[0]["queue_destination"] == "KITCHEN"
    assert Decimal(items.json()[0]["final_base_price"]) == Decimal("110.06")

    qr = client.get(
        f"/api/v1/staff/locations/{ids['location_a']}/tables/{ids['table']}/qr"
    )
    assert qr.status_code == 200, qr.text
    token = qr.json()["menu_url"].rsplit("/", 1)[-1]
    public_menu = client.get(f"/api/v1/public/tables/{token}")
    assert public_menu.status_code == 200, public_menu.text
    assert public_menu.json()["charge_disclosure"] == "Displayed prices include VAT and service charge."

    missing_required = client.post(
        f"/api/v1/public/tables/{token}/menu/validate",
        json={"menu_item_id": ids["item"], "modifier_option_ids": [], "quantity": 3},
    )
    assert missing_required.status_code == 422
    valid = client.post(
        f"/api/v1/public/tables/{token}/menu/validate",
        json={
            "menu_item_id": ids["item"],
            "modifier_option_ids": [ids["option"]],
            "quantity": 3,
        },
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["pricing"] == {
        "item_subtotal": "300.15",
        "modifier_subtotal": "0.15",
        "subtotal": "300.30",
        "vat": "22.52",
        "service_charge": "7.51",
        "total": "330.33",
        "currency": "NGN",
    }
    assert client.post(
        f"/api/v1/public/tables/{token}/menu/validate",
        json={
            "menu_item_id": ids["item"],
            "modifier_option_ids": [ids["option"], ids["option"]],
        },
    ).status_code == 422

    unavailable = client.patch(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{ids['item']}/modifier-options/{ids['option']}",
        json={"available": False},
    )
    assert unavailable.status_code == 200, unavailable.text
    assert client.post(
        f"/api/v1/public/tables/{token}/menu/validate",
        json={"menu_item_id": ids["item"], "modifier_option_ids": [ids["option"]]},
    ).status_code == 409
    sold_out = client.post(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{ids['item']}/sold-out",
        json={"sold_out": True, "reason": "Kitchen stock"},
    )
    assert sold_out.status_code == 200, sold_out.text
    assert client.post(
        f"/api/v1/public/tables/{token}/menu/validate",
        json={"menu_item_id": ids["item"], "modifier_option_ids": []},
    ).status_code == 409
    channel = staff_channel(ids["tenant_a"], ids["location_a"], StaffRole.MANAGER.value)
    events = asyncio.run(bus.replay(channel, 0))
    assert any(event.type.value == "menu_availability.changed" for event in events)


def test_menu_category_destination_crud_and_relationship_persistence(harness: dict) -> None:
    configure_mappers()
    client = harness["client"]
    ids = harness["ids"]
    SessionFactory = harness["Session"]
    login(client, "manager@tenant-a.example.com")
    category = client.post(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/categories",
        json={"name": "Cold bar", "sort_order": 20},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]
    drink = client.post(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items",
        json={
            "name": "Zobo",
            "description": "Hibiscus",
            "category_id": category_id,
            "item_type": "DRINK",
            "queue_destination": "BAR",
            "base_price": "1000.00",
        },
    )
    assert drink.status_code == 201, drink.text
    drink_id = drink.json()["id"]
    assert drink.json()["queue_destination"] == "BAR"
    renamed = client.patch(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/categories/{category_id}",
        json={"name": "Drinks"},
    )
    assert renamed.status_code == 200, renamed.text
    with SessionFactory() as db:
        row = db.get(MenuItem, drink_id)
        assert row.menu_category.id == category_id
        assert row.menu_category.name == "Drinks"
        assert row.category == "Drinks"
        assert row.location.id == ids["location_a"]
        assert {item.id for item in row.menu_category.items} == {drink_id}
    assert client.delete(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/categories/{category_id}"
    ).status_code == 409
    login(client, "manager@tenant-b.example.com")
    assert client.get(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items"
    ).status_code == 404


def test_prep_staff_menu_authority_is_station_scoped_and_noncommercial(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    location_path = f"/api/v1/staff/locations/{ids['location_a']}/menu"

    login(client, "chef@tenant-a.example.com")
    chef_items = client.get(f"{location_path}/items")
    assert chef_items.status_code == 200, chef_items.text
    assert [row["id"] for row in chef_items.json()] == [ids["item"]]
    assert client.patch(
        f"{location_path}/items/{ids['item']}", json={"description": "Fresh from the grill"}
    ).status_code == 200
    assert client.patch(
        f"{location_path}/items/{ids['item']}", json={"base_price": "1.00"}
    ).status_code == 403
    assert client.patch(
        f"{location_path}/items/{ids['item']}", json={"category_id": ids["category"]}
    ).status_code == 403
    assert client.patch(
        f"{location_path}/items/{ids['drink']}", json={"description": "Nope"}
    ).status_code == 403
    assert client.post(
        f"{location_path}/items/{ids['item']}/sold-out", json={"sold_out": True}
    ).status_code == 200
    assert client.post(
        f"{location_path}/items/{ids['drink']}/sold-out", json={"sold_out": True}
    ).status_code == 403
    created_food = client.post(
        f"{location_path}/items",
        json={
            "name": "Plantain",
            "category_id": ids["category"],
            "item_type": "FOOD",
            "queue_destination": "KITCHEN",
            "base_price": "500.00",
        },
    )
    assert created_food.status_code == 201, created_food.text
    assert client.post(
        f"{location_path}/items",
        json={
            "name": "Wine",
            "category_id": ids["category"],
            "item_type": "DRINK",
            "queue_destination": "BAR",
            "base_price": "500.00",
        },
    ).status_code == 403
    assert client.post(f"{location_path}/categories", json={"name": "Chef cannot add this"}).status_code == 403
    assert client.post(
        f"{location_path}/items/{ids['item']}/modifier-groups", json={"name": "Chef cannot add this"}
    ).status_code == 403

    login(client, "bartender@tenant-a.example.com")
    bartender_items = client.get(f"{location_path}/items")
    assert bartender_items.status_code == 200, bartender_items.text
    assert [row["id"] for row in bartender_items.json()] == [ids["drink"]]
    assert client.patch(
        f"{location_path}/items/{ids['drink']}", json={"name": "Chilled Zobo"}
    ).status_code == 200
    assert client.post(
        f"{location_path}/items/{ids['drink']}/sold-out", json={"sold_out": True}
    ).status_code == 200
    assert client.post(
        f"{location_path}/items",
        json={
            "name": "Beer",
            "category_id": ids["category"],
            "item_type": "DRINK",
            "queue_destination": "BAR",
            "base_price": "900.00",
        },
    ).status_code == 201


def test_table_and_complete_menu_administration_crud(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    login(client, "manager@tenant-a.example.com")
    table = client.post(
        f"/api/v1/staff/locations/{ids['location_a']}/tables",
        json={"label": "T2", "capacity": 6},
    )
    assert table.status_code == 201, table.text
    table_id = table.json()["id"]
    resized = client.patch(
        f"/api/v1/staff/locations/{ids['location_a']}/tables/{table_id}",
        json={"capacity": 8},
    )
    assert resized.status_code == 200, resized.text
    assert resized.json()["capacity"] == 8
    assert client.delete(
        f"/api/v1/staff/locations/{ids['location_a']}/tables/{table_id}"
    ).status_code == 204

    category = client.post(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/categories",
        json={"name": "Desserts"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]
    item = client.post(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items",
        json={
            "name": "Cake",
            "description": "Chocolate",
            "category_id": category_id,
            "item_type": "FOOD",
            "queue_destination": "KITCHEN",
            "base_price": "2500.00",
        },
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]
    updated_item = client.patch(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{item_id}",
        json={"base_price": "2600.00"},
    )
    assert updated_item.status_code == 200, updated_item.text
    group = client.post(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{item_id}/modifier-groups",
        json={"name": "Toppings", "minimum_selections": 0, "maximum_selections": 2},
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    changed_group = client.patch(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{item_id}/modifier-groups/{group_id}",
        json={"maximum_selections": 1},
    )
    assert changed_group.status_code == 200, changed_group.text
    option = client.post(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{item_id}/modifier-groups/{group_id}/options",
        json={"name": "Cream", "price_delta": "100.00"},
    )
    assert option.status_code == 201, option.text
    option_id = option.json()["id"]
    assert client.patch(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{item_id}/modifier-options/{option_id}",
        json={"price_delta": "150.00"},
    ).status_code == 200
    assert client.delete(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{item_id}/modifier-options/{option_id}"
    ).status_code == 204
    assert client.delete(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{item_id}/modifier-groups/{group_id}"
    ).status_code == 204
    assert client.delete(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/items/{item_id}"
    ).status_code == 204
    assert client.delete(
        f"/api/v1/staff/locations/{ids['location_a']}/menu/categories/{category_id}"
    ).status_code == 204


def test_qr_daily_rotation_hash_only_forced_invalidation_guessing_and_audit(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    SessionFactory = harness["Session"]
    bus = harness["bus"]
    login(client, "waiter@tenant-a.example.com")
    route = f"/api/v1/staff/locations/{ids['location_a']}/tables/{ids['table']}/qr"
    first = client.get(route)
    assert first.status_code == 200, first.text
    assert first.json()["presentation"] == "DIGITAL"
    assert first.json()["printable"] is True
    assert client.get(route).json()["qr_value"] == first.json()["qr_value"]
    raw = first.json()["menu_url"].rsplit("/", 1)[-1]
    with SessionFactory() as db:
        stored = db.scalar(select(TableQrToken).where(TableQrToken.table_id == ids["table"]))
        assert stored.token_hash not in raw
        assert raw not in stored.token_hash
    assert client.get("/api/v1/public/tables/chw_qr_guessed-token").status_code == 404
    assert client.get(f"/api/v1/public/tables/{raw}").status_code == 200

    regenerated = client.post(f"{route}/regenerate")
    assert regenerated.status_code == 200, regenerated.text
    replacement = regenerated.json()["menu_url"].rsplit("/", 1)[-1]
    assert replacement != raw
    assert client.get(f"/api/v1/public/tables/{raw}").status_code == 404
    assert client.get(f"/api/v1/public/tables/{replacement}").status_code == 200
    with SessionFactory() as db:
        audits = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.subject_id == ids["table"],
                    AuditEvent.event_type == "TABLE_QR_REGENERATED",
                )
            )
        )
        assert len(audits) == 1
        rows = list(db.scalars(select(TableQrToken).where(TableQrToken.table_id == ids["table"])))
        assert len(rows) == 2
        assert sum(row.invalidated_at is None for row in rows) == 1
    channel = staff_channel(ids["tenant_a"], ids["location_a"], StaffRole.WAITER.value)
    assert any(
        event.payload["change"] == "qr_regenerated"
        for event in asyncio.run(bus.replay(channel, 0))
    )


def test_qr_rotates_on_location_local_day_boundary(harness: dict) -> None:
    ids = harness["ids"]
    SessionFactory = harness["Session"]
    with SessionFactory() as db:
        location = db.get(Location, ids["location_a"])
        table = db.get(DiningTable, ids["table"])
        location.timezone = "Pacific/Kiritimati"
        first_now = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
        first = issue_table_qr(
            db,
            table=table,
            location=location,
            secret=get_settings().session_signing_secret,
            now=first_now,
        )
        db.commit()
        assert resolve_table_qr(db, first.raw_token, now=first_now)[1].id == table.id
        second_now = first_now + timedelta(hours=1)
        second = issue_table_qr(
            db,
            table=table,
            location=location,
            secret=get_settings().session_signing_secret,
            now=second_now,
        )
        db.commit()
        assert first.row.issued_on != second.row.issued_on
        assert first.raw_token != second.raw_token
        with pytest.raises(InvalidTableQr):
            resolve_table_qr(db, first.raw_token, now=second_now)
        assert resolve_table_qr(db, second.raw_token, now=second_now)[1].id == table.id


def test_table_activity_tracks_nonterminal_orders_and_open_visits(harness: dict) -> None:
    ids = harness["ids"]
    SessionFactory = harness["Session"]
    with SessionFactory() as db:
        table = db.get(DiningTable, ids["table"])
        assert not calculate_table_activity(db, table)
        order = Order(
            tenant_id=ids["tenant_a"],
            location_id=ids["location_a"],
            table_id=table.id,
            customer_id=ids["customer"],
            customer_tenant_record_id=ids["customer_record"],
            status=OrderStatus.SUBMITTED,
        )
        db.add(order)
        db.flush()
        assert calculate_table_activity(db, table)
        order.status = OrderStatus.PAID
        db.flush()
        assert not calculate_table_activity(db, table)
        visit = TableVisit(
            tenant_id=ids["tenant_a"],
            location_id=ids["location_a"],
            table_id=table.id,
            opened_by_order_id=order.id,
        )
        db.add(visit)
        db.flush()
        assert calculate_table_activity(db, table)
        visit.closed_at = datetime.now(UTC)
        db.flush()
        assert not calculate_table_activity(db, table)
