from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime

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
from app.core.security import hash_password  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app as production_app  # noqa: E402
from app.models import (  # noqa: E402
    InvitationStatus,
    Location,
    OperatingHour,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    Tenant,
)
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.platform_admin import router as platform_admin_router  # noqa: E402


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
        tenant = Tenant(name="Existing Tenant")
        db.add(tenant)
        db.flush()
        location = Location(tenant_id=tenant.id, name="Existing Location", address="1 Existing Street")
        db.add(location)
        db.flush()
        password_hash = hash_password(PASSWORD)
        platform = StaffAccount(
            name="Platform Admin",
            email="platform@chowly.ng",
            password_hash=password_hash,
            invitation_status=InvitationStatus.ACCEPTED,
            accepted_at=datetime.now(UTC),
            is_active=True,
            is_platform_admin=True,
        )
        manager = StaffAccount(
            tenant_id=tenant.id,
            name="Manager",
            email="manager@tenant.ng",
            password_hash=password_hash,
            invitation_status=InvitationStatus.ACCEPTED,
            accepted_at=datetime.now(UTC),
            is_active=True,
        )
        db.add_all([platform, manager])
        db.flush()
        db.add_all(
            [
                StaffRoleAssignment(tenant_id=tenant.id, staff_id=manager.id, role=StaffRole.MANAGER),
                StaffLocationAssignment(tenant_id=tenant.id, location_id=location.id, staff_id=manager.id),
            ]
        )
        db.commit()

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(platform_admin_router)

    def override_db() -> Generator[Session, None, None]:
        with SessionFactory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield {"client": client, "Session": SessionFactory}
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, email: str) -> None:
    response = client.post("/api/v1/staff/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    # Make the authenticated principal explicit for this isolated router harness.
    client.headers["Authorization"] = f"Bearer {client.cookies.get(get_settings().session_cookie_name)}"


def valid_payload(**overrides: object) -> dict:
    body = {
        "tenant_name": "New Tenant Hospitality",
        "initial_location": {
            "name": "New Tenant Lekki",
            "address": "24 Admiralty Way, Lekki",
            "currency": "ngn",
            "vat_rate": "0.075",
            "service_charge_rate": "0.05",
            "timezone": "Africa/Lagos",
            "is_open": True,
        },
        "operating_hours": [
            {"weekday": 0, "opens_at": "09:00:00", "closes_at": "22:00:00"},
            {"weekday": 1, "is_closed": True},
        ],
        "owner_invitation": {"name": "New Owner", "email": "owner@new-tenant.ng"},
    }
    body.update(overrides)
    return body


def test_platform_admin_bootstraps_owned_tenant_location_hours_and_owner(harness: dict) -> None:
    client = harness["client"]
    SessionFactory = harness["Session"]
    login(client, "platform@chowly.ng")

    response = client.post("/api/v1/platform/tenants/bootstrap", json=valid_payload())
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["initial_location"]["tenant_id"] == created["tenant_id"]
    assert created["initial_location"]["currency"] == "NGN"
    assert len(created["initial_location"]["operating_hours"]) == 2
    assert created["owner_invitation"]["acceptance_token"]

    with SessionFactory() as db:
        tenant = db.get(Tenant, created["tenant_id"])
        location = db.get(Location, created["initial_location"]["id"])
        assert tenant and location and location.tenant_id == tenant.id
        hours = list(db.scalars(select(OperatingHour).where(OperatingHour.location_id == location.id)))
        assert {row.tenant_id for row in hours} == {tenant.id}
        owner = db.scalar(select(StaffAccount).where(StaffAccount.email == "owner@new-tenant.ng"))
        assert owner and owner.tenant_id == tenant.id
        assert owner.invitation_status == InvitationStatus.PENDING
        assert owner.invitation_token_hash != created["owner_invitation"]["acceptance_token"]
        assignment = db.scalar(select(StaffLocationAssignment).where(StaffLocationAssignment.staff_id == owner.id))
        assert assignment and assignment.tenant_id == tenant.id and assignment.location_id == location.id


def test_bootstrap_denies_non_platform_staff_and_validates_the_complete_location_contract(harness: dict) -> None:
    client = harness["client"]
    login(client, "manager@tenant.ng")
    assert client.post("/api/v1/platform/tenants/bootstrap", json=valid_payload()).status_code == 403

    login(client, "platform@chowly.ng")
    invalid_timezone = valid_payload(initial_location={**valid_payload()["initial_location"], "timezone": "Moon/Base"})
    assert client.post("/api/v1/platform/tenants/bootstrap", json=invalid_timezone).status_code == 422
    duplicate_hours = valid_payload(operating_hours=[
        {"weekday": 0, "opens_at": "09:00:00", "closes_at": "22:00:00"},
        {"weekday": 0, "opens_at": "10:00:00", "closes_at": "23:00:00"},
    ])
    assert client.post("/api/v1/platform/tenants/bootstrap", json=duplicate_hours).status_code == 422


def test_platform_bootstrap_is_mounted_in_production_openapi() -> None:
    schema = production_app.openapi()
    assert "/api/v1/platform/tenants/bootstrap" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/platform/tenants/bootstrap"]
