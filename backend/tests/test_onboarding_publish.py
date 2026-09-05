from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["CHOWLY_ENVIRONMENT"] = "test"
os.environ["CHOWLY_SESSION_SIGNING_SECRET"] = "test-session-secret-with-more-than-32-characters"

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.models import (  # noqa: E402
    DiningTable,
    InvitationStatus,
    Location,
    MenuCategory,
    MenuItem,
    MenuItemType,
    OperatingHour,
    QueueDestination,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    Tenant,
    TenantLifecycle,
)
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.onboarding import router as onboarding_router  # noqa: E402
from app.routers.public_restaurants import router as public_restaurants_router  # noqa: E402


PASSWORD = "CorrectHorse!2026"


@pytest.fixture()
def harness() -> Generator[dict, None, None]:
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionFactory() as db:
        tenant = Tenant(name="Private Restaurant", lifecycle=TenantLifecycle.PENDING_SETUP)
        db.add(tenant)
        db.flush()
        location = Location(tenant_id=tenant.id, name="Lekki", address="1 Admiralty Way", is_active=True)
        owner = StaffAccount(tenant_id=tenant.id, name="Owner", email="owner@private.ng", password_hash=hash_password(PASSWORD), invitation_status=InvitationStatus.ACCEPTED, accepted_at=datetime.now(UTC), is_active=True)
        manager = StaffAccount(tenant_id=tenant.id, name="Manager", email="manager@private.ng", password_hash=hash_password(PASSWORD), invitation_status=InvitationStatus.ACCEPTED, accepted_at=datetime.now(UTC), is_active=True)
        db.add_all([location, owner, manager])
        db.flush()
        db.add_all([
            StaffRoleAssignment(tenant_id=tenant.id, staff_id=owner.id, role=StaffRole.TENANT_OWNER),
            StaffRoleAssignment(tenant_id=tenant.id, staff_id=manager.id, role=StaffRole.MANAGER),
            StaffLocationAssignment(tenant_id=tenant.id, location_id=location.id, staff_id=owner.id),
            StaffLocationAssignment(tenant_id=tenant.id, location_id=location.id, staff_id=manager.id),
        ])
        db.commit()
        ids = {"tenant": tenant.id, "location": location.id}

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(onboarding_router)
    app.include_router(public_restaurants_router)

    def override_db() -> Generator[Session, None, None]:
        with SessionFactory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield {"client": client, "Session": SessionFactory, "ids": ids}
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, email: str) -> None:
    response = client.post("/api/v1/staff/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {client.cookies.get(get_settings().session_cookie_name)}"


def make_ready(session: Session, ids: dict[str, str]) -> None:
    location_id, tenant_id = ids["location"], ids["tenant"]
    category = MenuCategory(tenant_id=tenant_id, location_id=location_id, name="Mains", is_active=True)
    session.add_all([
        OperatingHour(tenant_id=tenant_id, location_id=location_id, weekday=0, opens_at=time(9), closes_at=time(21)),
        DiningTable(tenant_id=tenant_id, location_id=location_id, label="A1", capacity=2, is_enabled=True),
        category,
    ])
    session.flush()
    session.add(MenuItem(tenant_id=tenant_id, location_id=location_id, category_id=category.id, category=category.name, name="Jollof rice", item_type=MenuItemType.FOOD, queue_destination=QueueDestination.KITCHEN, base_price=2500, available=True))
    session.commit()


def test_owner_can_publish_only_after_all_setup_prerequisites(harness: dict) -> None:
    client, SessionFactory, ids = harness["client"], harness["Session"], harness["ids"]
    login(client, "owner@private.ng")

    blocked = client.post("/api/v1/onboarding/publish")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["missing"] == [
        "Set opening hours for at least one active location.",
        "Add at least one enabled dining table.",
        "Add at least one available menu item in an active menu category.",
    ]

    with SessionFactory() as db:
        make_ready(db, ids)
    published = client.post("/api/v1/onboarding/publish")
    assert published.status_code == 200, published.text
    assert published.json()["lifecycle"] == "ACTIVE"
    assert client.get("/api/v1/public/restaurants/private-restaurant").status_code == 200
    assert client.post("/api/v1/onboarding/publish").json()["message"] == "Your restaurant is already published."


def test_only_tenant_owner_can_publish(harness: dict) -> None:
    client = harness["client"]
    login(client, "manager@private.ng")
    assert client.post("/api/v1/onboarding/publish").status_code == 403
