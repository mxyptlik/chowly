from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["CHOWLY_ENVIRONMENT"] = "test"
os.environ["CHOWLY_SESSION_SIGNING_SECRET"] = "test-session-secret-with-more-than-32-characters"
os.environ["CHOWLY_REALTIME_SIGNING_SECRET"] = "test-realtime-secret-with-more-than-32-characters"

from app.auth import CurrentStaff, create_invitation, current_staff_from_account  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password, issue_staff_session  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.dependencies import (  # noqa: E402
    assert_order_operator,
    assert_station_access,
    customer_contact_payload,
    get_current_staff,
    require_location_access,
    require_platform_admin,
    require_roles,
    scoped_resource_or_404,
)
from app.events import RealtimeTokenCodec  # noqa: E402
from app.models import (  # noqa: E402
    Customer,
    InvitationStatus,
    Location,
    QueueDestination,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    Tenant,
)
from app.main import app as production_app  # noqa: E402
from app.routers.auth import router as auth_router  # noqa: E402
from app.seed import DEMO_PASSWORD, seed  # noqa: E402


TEST_PASSWORD = "CorrectHorse!2026"


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
        tenant_a = Tenant(name="Tenant A")
        tenant_b = Tenant(name="Tenant B")
        db.add_all([tenant_a, tenant_b])
        db.flush()
        location_a1 = Location(tenant_id=tenant_a.id, name="A One", address="1 A Street")
        location_a2 = Location(tenant_id=tenant_a.id, name="A Two", address="2 A Street")
        location_b1 = Location(tenant_id=tenant_b.id, name="B One", address="1 B Street")
        db.add_all([location_a1, location_a2, location_b1])
        db.flush()
        password_hash = hash_password(TEST_PASSWORD)

        def account(
            name: str,
            email: str,
            tenant: Tenant | None,
            roles: list[StaffRole],
            locations: list[Location],
            *,
            platform: bool = False,
        ) -> StaffAccount:
            row = StaffAccount(
                tenant_id=tenant.id if tenant else None,
                name=name,
                email=email,
                password_hash=password_hash,
                invitation_status=InvitationStatus.ACCEPTED,
                accepted_at=datetime.now(UTC),
                is_active=True,
                is_platform_admin=platform,
            )
            db.add(row)
            db.flush()
            if tenant:
                for role in roles:
                    db.add(StaffRoleAssignment(tenant_id=tenant.id, staff_id=row.id, role=role))
                for location in locations:
                    db.add(StaffLocationAssignment(tenant_id=tenant.id, location_id=location.id, staff_id=row.id))
            return row

        owner = account("Owner", "owner@tenant-a.ng", tenant_a, [StaffRole.TENANT_OWNER], [location_a1, location_a2])
        manager = account("Manager", "manager@tenant-a.ng", tenant_a, [StaffRole.MANAGER], [location_a1])
        waiter = account("Waiter", "waiter@tenant-a.ng", tenant_a, [StaffRole.WAITER], [location_a1])
        waiter_a2 = account("Waiter A2", "waiter2@tenant-a.ng", tenant_a, [StaffRole.WAITER], [location_a2])
        chef = account("Chef", "chef@tenant-a.ng", tenant_a, [StaffRole.CHEF], [location_a1])
        other_manager = account("Other manager", "manager@tenant-b.ng", tenant_b, [StaffRole.MANAGER], [location_b1])
        platform = account("Platform", "platform@chowly.ng", None, [], [], platform=True)
        customer = Customer(name="Diner", phone="+2348000000001", email="diner@example.test")
        db.add(customer)
        db.commit()
        ids = {
            "tenant_a": tenant_a.id,
            "tenant_b": tenant_b.id,
            "location_a1": location_a1.id,
            "location_a2": location_a2.id,
            "location_b1": location_b1.id,
            "owner": owner.id,
            "manager": manager.id,
            "waiter": waiter.id,
            "waiter_a2": waiter_a2.id,
            "chef": chef.id,
            "other_manager": other_manager.id,
            "platform": platform.id,
            "customer": customer.id,
        }

    app = FastAPI()
    app.include_router(auth_router)

    def override_db() -> Generator[Session, None, None]:
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_db

    @app.get("/api/v1/test/manager")
    def manager_only(_: CurrentStaff = Depends(require_roles(StaffRole.MANAGER))) -> dict:
        return {"ok": True}

    @app.get("/api/v1/test/platform")
    def platform_only(_: CurrentStaff = Depends(require_platform_admin)) -> dict:
        return {"ok": True}

    @app.get("/api/v1/test/location-path/{location_id}")
    def location_path(_: CurrentStaff = Depends(require_location_access())) -> dict:
        return {"ok": True}

    @app.get("/api/v1/test/locations/{resource_id}")
    def location_resource(
        resource_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(get_current_staff),
    ) -> dict:
        location = scoped_resource_or_404(db, Location, resource_id, current)
        return {"id": location.id}

    @app.get("/api/v1/test/order-operator/{location_id}/{owner_id}")
    def order_operator(
        location_id: str,
        owner_id: str,
        current: CurrentStaff = Depends(get_current_staff),
    ) -> dict:
        assert_order_operator(current, location_id=location_id, owner_id=owner_id)
        return {"ok": True}

    @app.get("/api/v1/test/station/{location_id}/{destination}")
    def station(
        location_id: str,
        destination: QueueDestination,
        current: CurrentStaff = Depends(get_current_staff),
    ) -> dict:
        assert_station_access(current, location_id=location_id, destination=destination)
        return {"ok": True}

    @app.get("/api/v1/test/contact/{location_id}/{owner_id}")
    def contact(
        location_id: str,
        owner_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(get_current_staff),
    ) -> dict:
        customer_row = db.get(Customer, ids["customer"])
        return {
            "contact": customer_contact_payload(
                current,
                location_id=location_id,
                order_owner_id=owner_id,
                customer=customer_row,
            )
        }

    with TestClient(app) as client:
        yield {
            "client": client,
            "Session": TestingSession,
            "ids": ids,
        }
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, email: str) -> dict:
    response = client.post("/api/v1/staff/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def test_login_session_refresh_active_location_and_logout(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    current = login(client, "owner@tenant-a.ng")
    assert current["roles"] == ["TENANT_OWNER"]
    assert {row["id"] for row in current["locations"]} == {ids["location_a1"], ids["location_a2"]}
    assert current["active_tenant_id"] == ids["tenant_a"]

    cookie_name = get_settings().session_cookie_name
    original_cookie = client.cookies.get(cookie_name)
    refreshed = client.post("/api/v1/staff/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get(cookie_name) != original_cookie

    selected = client.post(
        "/api/v1/staff/auth/active-location",
        json={"location_id": ids["location_a2"]},
    )
    assert selected.status_code == 200
    assert selected.json()["active_location_id"] == ids["location_a2"]
    assert client.get("/api/v1/staff/auth/session").json()["active_location_id"] == ids["location_a2"]

    logged_out = client.post("/api/v1/staff/auth/logout")
    assert logged_out.status_code == 204
    assert client.get("/api/v1/staff/auth/session").status_code == 401


def test_invite_is_hashed_one_time_and_supports_multi_role_location(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    SessionFactory = harness["Session"]
    login(client, "owner@tenant-a.ng")
    invited = client.post(
        "/api/v1/staff/auth/invitations",
        json={
            "name": "Multi Station",
            "email": "multi@tenant-a.ng",
            "roles": ["WAITER", "CHEF"],
            "location_ids": [ids["location_a1"], ids["location_a2"]],
        },
    )
    assert invited.status_code == 201, invited.text
    raw_token = invited.json()["acceptance_token"]
    with SessionFactory() as db:
        account = db.scalar(select(StaffAccount).where(StaffAccount.email == "multi@tenant-a.ng"))
        assert account.invitation_token_hash
        assert account.invitation_token_hash != raw_token
        assert account.password_hash is None

    accepted = client.post(
        "/api/v1/staff/auth/invitations/accept",
        json={"token": raw_token, "password": TEST_PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    assert set(accepted.json()["roles"]) == {"WAITER", "CHEF"}
    assert {row["id"] for row in accepted.json()["locations"]} == {ids["location_a1"], ids["location_a2"]}
    assert client.post(
        "/api/v1/staff/auth/invitations/accept",
        json={"token": raw_token, "password": TEST_PASSWORD},
    ).status_code == 404
    client.post("/api/v1/staff/auth/logout")
    assert login(client, "multi@tenant-a.ng")["staff_id"] == invited.json()["staff_id"]


def test_manager_cannot_grant_manager_or_foreign_location(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    login(client, "manager@tenant-a.ng")
    cannot_escalate = client.post(
        "/api/v1/staff/auth/invitations",
        json={
            "name": "Escalation",
            "email": "escalation@tenant-a.ng",
            "roles": ["MANAGER"],
            "location_ids": [ids["location_a1"]],
        },
    )
    assert cannot_escalate.status_code == 403
    foreign_location = client.post(
        "/api/v1/staff/auth/invitations",
        json={
            "name": "Foreign",
            "email": "foreign@tenant-a.ng",
            "roles": ["WAITER"],
            "location_ids": [ids["location_b1"]],
        },
    )
    assert foreign_location.status_code == 403
    allowed_staff_invite = client.post(
        "/api/v1/staff/auth/invitations",
        json={
            "name": "Bar Support",
            "email": "bar-support@tenant-a.ng",
            "roles": ["BARTENDER"],
            "location_ids": [ids["location_a1"]],
        },
    )
    assert allowed_staff_invite.status_code == 201


def test_tenant_owner_can_manage_only_own_staff_assignments_with_safe_guards(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]

    login(client, "manager@tenant-a.ng")
    assert client.get("/api/v1/staff/auth/members").status_code == 403

    login(client, "owner@tenant-a.ng")
    members = client.get("/api/v1/staff/auth/members")
    assert members.status_code == 200, members.text
    assert {member["id"] for member in members.json()} == {
        ids["owner"], ids["manager"], ids["waiter"], ids["waiter_a2"], ids["chef"]
    }
    assert client.get(f"/api/v1/staff/auth/members/{ids['other_manager']}").status_code == 404

    upgraded = client.put(
        f"/api/v1/staff/auth/members/{ids['waiter']}/assignments",
        json={
            "roles": ["WAITER", "CHEF"],
            "location_ids": [ids["location_a1"], ids["location_a2"]],
        },
    )
    assert upgraded.status_code == 200, upgraded.text
    assert set(upgraded.json()["roles"]) == {"WAITER", "CHEF"}
    assert {location["id"] for location in upgraded.json()["locations"]} == {
        ids["location_a1"], ids["location_a2"]
    }

    foreign_location = client.put(
        f"/api/v1/staff/auth/members/{ids['waiter']}/assignments",
        json={"roles": ["WAITER"], "location_ids": [ids["location_b1"]]},
    )
    assert foreign_location.status_code == 409
    platform_role = client.put(
        f"/api/v1/staff/auth/members/{ids['waiter']}/assignments",
        json={"roles": ["PLATFORM_ADMIN"], "location_ids": [ids["location_a1"]]},
    )
    assert platform_role.status_code == 409

    # Establish a second owner, then prove the actor cannot remove their own
    # owner authority even though another owner remains.
    second_owner = client.put(
        f"/api/v1/staff/auth/members/{ids['manager']}/assignments",
        json={"roles": ["MANAGER", "TENANT_OWNER"], "location_ids": [ids["location_a1"]]},
    )
    assert second_owner.status_code == 200, second_owner.text
    self_demote = client.put(
        f"/api/v1/staff/auth/members/{ids['owner']}/assignments",
        json={"roles": ["MANAGER"], "location_ids": [ids["location_a1"]]},
    )
    assert self_demote.status_code == 409
    assert "own tenant-owner" in self_demote.json()["detail"]

    # The sole-owner invariant still protects a tenant if the remaining owner
    # tries to demote the other owner.
    demote_second_owner = client.put(
        f"/api/v1/staff/auth/members/{ids['manager']}/assignments",
        json={"roles": ["MANAGER"], "location_ids": [ids["location_a1"]]},
    )
    assert demote_second_owner.status_code == 200
    only_owner = client.put(
        f"/api/v1/staff/auth/members/{ids['owner']}/assignments",
        json={"roles": ["MANAGER"], "location_ids": [ids["location_a1"]]},
    )
    assert only_owner.status_code == 409
    assert "at least one tenant owner" in only_owner.json()["detail"]


def test_expired_used_and_invalid_sessions_are_rejected(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    SessionFactory = harness["Session"]
    with SessionFactory() as db:
        owner = db.get(StaffAccount, ids["owner"])
        inviter = current_staff_from_account(db, owner)
        _, expired_raw = create_invitation(
            db,
            inviter=inviter,
            name="Expired",
            email="expired@tenant-a.ng",
            roles=[StaffRole.WAITER],
            location_ids=[ids["location_a1"]],
            ttl=timedelta(hours=1),
            now=datetime.now(UTC) - timedelta(days=2),
        )
    expired = client.post(
        "/api/v1/staff/auth/invitations/accept",
        json={"token": expired_raw, "password": TEST_PASSWORD},
    )
    assert expired.status_code == 410

    settings = get_settings()
    old = datetime.now(UTC) - timedelta(hours=2)
    expired_session = issue_staff_session(
        staff_id=ids["waiter"],
        tenant_id=ids["tenant_a"],
        active_location_id=ids["location_a1"],
        secret=settings.session_signing_secret,
        ttl=timedelta(minutes=1),
        now=old,
    )
    client.cookies.set(settings.session_cookie_name, expired_session, path="/api/v1")
    assert client.get("/api/v1/staff/auth/session").status_code == 401
    client.cookies.set(settings.session_cookie_name, expired_session + "tampered", path="/api/v1")
    assert client.get("/api/v1/staff/auth/session").status_code == 401


def test_roles_locations_ownership_stations_and_enumeration_are_isolated(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    login(client, "waiter@tenant-a.ng")
    assert client.get("/api/v1/test/manager").status_code == 403
    assert client.get(f"/api/v1/test/location-path/{ids['location_a1']}").status_code == 200
    assert client.get(f"/api/v1/test/location-path/{ids['location_a2']}").status_code == 404
    assert client.get(f"/api/v1/test/locations/{ids['location_a2']}").status_code == 404
    assert client.get(f"/api/v1/test/locations/{ids['location_b1']}").status_code == 404
    assert client.get(
        f"/api/v1/test/order-operator/{ids['location_a1']}/{ids['waiter']}"
    ).status_code == 200
    assert client.get(
        f"/api/v1/test/order-operator/{ids['location_a1']}/{ids['waiter_a2']}"
    ).status_code == 403
    assert client.get(
        f"/api/v1/test/station/{ids['location_a1']}/KITCHEN"
    ).status_code == 403

    login(client, "chef@tenant-a.ng")
    assert client.get(f"/api/v1/test/station/{ids['location_a1']}/KITCHEN").status_code == 200
    assert client.get(f"/api/v1/test/station/{ids['location_a1']}/BAR").status_code == 403

    login(client, "manager@tenant-a.ng")
    assert client.get(f"/api/v1/test/locations/{ids['location_a1']}").status_code == 200
    assert client.get(f"/api/v1/test/locations/{ids['location_b1']}").status_code == 404
    assert client.get(
        f"/api/v1/test/order-operator/{ids['location_a1']}/{ids['waiter']}"
    ).status_code == 200


def test_customer_contact_never_reaches_prep_roles_or_unowned_waiters(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    login(client, "waiter@tenant-a.ng")
    owned = client.get(f"/api/v1/test/contact/{ids['location_a1']}/{ids['waiter']}").json()
    assert owned["contact"]["phone"] == "+2348000000001"
    not_owned = client.get(f"/api/v1/test/contact/{ids['location_a1']}/{ids['waiter_a2']}").json()
    assert not_owned["contact"] is None
    login(client, "chef@tenant-a.ng")
    assert client.get(f"/api/v1/test/contact/{ids['location_a1']}/{ids['waiter']}").json()["contact"] is None
    login(client, "manager@tenant-a.ng")
    assert client.get(f"/api/v1/test/contact/{ids['location_a1']}/{ids['waiter']}").json()["contact"]["email"] == "diner@example.test"


def test_platform_boundary_and_scoped_realtime_grants(harness: dict) -> None:
    client = harness["client"]
    ids = harness["ids"]
    login(client, "manager@tenant-a.ng")
    assert client.get("/api/v1/test/platform").status_code == 403
    grant_response = client.post(
        "/api/v1/staff/auth/realtime-grant",
        json={"location_id": ids["location_a1"], "role": "MANAGER"},
    )
    assert grant_response.status_code == 200
    grant = RealtimeTokenCodec(get_settings().realtime_signing_secret).decode(grant_response.json()["token"])
    assert grant.permits_staff(ids["tenant_a"], ids["location_a1"], "MANAGER")
    assert not grant.permits_staff(ids["tenant_a"], ids["location_a2"], "MANAGER")
    assert client.post(
        "/api/v1/staff/auth/realtime-grant",
        json={"location_id": ids["location_a1"], "role": "CHEF"},
    ).status_code == 403

    login(client, "platform@chowly.ng")
    assert client.get("/api/v1/test/platform").status_code == 200


def test_all_legacy_staff_routes_require_session_before_caller_ids(harness: dict) -> None:
    """Regression proof for the prototype's former request-body authority flaw."""
    production_app.dependency_overrides[get_db] = lambda: iter((harness["Session"](),))
    client = TestClient(production_app)
    try:
        assert client.get("/api/v1/staff/orders").status_code == 401
        assert client.get("/api/v1/staff/members").status_code == 401
        assert client.get("/api/v1/staff/prep").status_code == 401
        assert client.post(
            "/api/v1/staff/orders/guessed/accept",
            json={"waiter_id": harness["ids"]["waiter"], "estimated_wait_minutes": 15},
        ).status_code == 401
        assert client.post(
            "/api/v1/staff/lines/guessed/claim",
            json={"staff_id": harness["ids"]["chef"]},
        ).status_code == 401
        assert client.post(
            "/api/v1/staff/orders/guessed/serve",
            json={"staff_id": harness["ids"]["waiter"]},
        ).status_code == 401
    finally:
        client.close()
        production_app.dependency_overrides.pop(get_db, None)


def test_demo_bootstrap_is_normalized_hashed_and_development_only(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionFactory() as db:
        seed(db)
        accounts = list(db.scalars(select(StaffAccount).order_by(StaffAccount.email)))
        # Seven pilot tenants with five roles each, plus one platform admin.
        assert len(accounts) == 36
        platform_admin = next(account for account in accounts if account.email == "platform.admin@demo.chowly.ng")
        assert platform_admin.is_platform_admin is True
        assert platform_admin.tenant_id is None
        assert all(account.password_hash and account.password_hash != DEMO_PASSWORD for account in accounts)
        assert all(account.invitation_status == InvitationStatus.ACCEPTED for account in accounts)
        assert db.scalar(select(StaffRoleAssignment.id).limit(1))
        assert db.scalar(select(StaffLocationAssignment.id).limit(1))

    Base.metadata.drop_all(engine)
    monkeypatch.setenv("CHOWLY_ENVIRONMENT", "production")
    monkeypatch.setenv("CHOWLY_SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("CHOWLY_SESSION_SIGNING_SECRET", "production-session-secret-01234567890123456789")
    monkeypatch.setenv("CHOWLY_REALTIME_SIGNING_SECRET", "production-realtime-secret-012345678901234567")
    get_settings.cache_clear()
    Base.metadata.create_all(engine)
    with SessionFactory() as db:
        seed(db)
        assert db.scalar(select(Tenant.id).limit(1)) is None
    monkeypatch.setenv("CHOWLY_ENVIRONMENT", "test")
    monkeypatch.setenv("CHOWLY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("CHOWLY_SESSION_SIGNING_SECRET", "test-session-secret-with-more-than-32-characters")
    monkeypatch.setenv("CHOWLY_REALTIME_SIGNING_SECRET", "test-realtime-secret-with-more-than-32-characters")
    get_settings.cache_clear()
    engine.dispose()
