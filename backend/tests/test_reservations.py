from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["CHOWLY_ENVIRONMENT"] = "test"
os.environ["CHOWLY_SESSION_SIGNING_SECRET"] = "test-session-secret-with-more-than-32-characters"
os.environ["CHOWLY_REALTIME_SIGNING_SECRET"] = "test-realtime-secret-with-more-than-32-characters"

from app.auth import CurrentStaff  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.dependencies import get_current_staff  # noqa: E402
from app.events import staff_channel  # noqa: E402
from app.models import (  # noqa: E402
    AuditEvent,
    Customer,
    CustomerTenantRecord,
    DiningTable,
    Location,
    OperatingHour,
    Reservation,
    ReservationStatus,
    StaffAccount,
    StaffLocationAssignment,
    StaffRole,
    StaffRoleAssignment,
    TableVisit,
    Tenant,
)
from app.realtime import InMemoryEventBus  # noqa: E402
from app.routers.reservations import create_reservations_router  # noqa: E402


LAGOS = ZoneInfo("Africa/Lagos")


def future_at(hour: int, *, days: int = 2) -> datetime:
    return (datetime.now(LAGOS) + timedelta(days=days)).replace(
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
    )


@pytest.fixture()
def harness() -> Generator[dict[str, object], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSession() as db:
        tenant_a = Tenant(name="Reservation tenant A")
        tenant_b = Tenant(name="Reservation tenant B")
        db.add_all([tenant_a, tenant_b])
        db.flush()
        location_a = Location(
            tenant_id=tenant_a.id,
            name="Lagos Dining Room",
            address="1 Marina",
            timezone="Africa/Lagos",
            is_active=True,
        )
        location_a2 = Location(
            tenant_id=tenant_a.id,
            name="Ikeja Dining Room",
            address="2 Allen",
            timezone="Africa/Lagos",
            is_active=True,
        )
        location_b = Location(
            tenant_id=tenant_b.id,
            name="Foreign Dining Room",
            address="3 Other",
            timezone="Africa/Lagos",
            is_active=True,
        )
        inactive = Location(
            tenant_id=tenant_a.id,
            name="Inactive Dining Room",
            address="4 Closed",
            timezone="Africa/Lagos",
            is_active=False,
        )
        db.add_all([location_a, location_a2, location_b, inactive])
        db.flush()
        for location in (location_a, location_a2, location_b, inactive):
            for weekday in range(7):
                db.add(
                    OperatingHour(
                        tenant_id=location.tenant_id,
                        location_id=location.id,
                        weekday=weekday,
                        opens_at=time(9),
                        closes_at=time(23),
                        is_closed=False,
                    )
                )
        table_a = DiningTable(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            label="A1",
            capacity=4,
        )
        small_table = DiningTable(
            tenant_id=tenant_a.id,
            location_id=location_a.id,
            label="A2",
            capacity=2,
        )
        table_a2 = DiningTable(
            tenant_id=tenant_a.id,
            location_id=location_a2.id,
            label="I1",
            capacity=8,
        )
        db.add_all([table_a, small_table, table_a2])
        db.flush()

        def staff(
            name: str,
            role: StaffRole,
            tenant: Tenant,
            location: Location,
        ) -> tuple[StaffAccount, CurrentStaff]:
            account = StaffAccount(tenant_id=tenant.id, name=name, email=f"{name.lower()}@example.test")
            db.add(account)
            db.flush()
            db.add(StaffRoleAssignment(tenant_id=tenant.id, staff_id=account.id, role=role))
            db.add(
                StaffLocationAssignment(
                    tenant_id=tenant.id,
                    location_id=location.id,
                    staff_id=account.id,
                )
            )
            principal = CurrentStaff(
                account=account,
                tenant_id=tenant.id,
                roles=frozenset({role}),
                location_ids=frozenset({location.id}),
                active_location_id=location.id,
                locations=(location,),
            )
            return account, principal

        manager_account, manager = staff("Manager", StaffRole.MANAGER, tenant_a, location_a)
        _, waiter = staff("Waiter", StaffRole.WAITER, tenant_a, location_a)
        _, manager_a2 = staff("ManagerA2", StaffRole.MANAGER, tenant_a, location_a2)
        _, foreign_manager = staff("ForeignManager", StaffRole.MANAGER, tenant_b, location_b)
        _, chef = staff("Chef", StaffRole.CHEF, tenant_a, location_a)
        db.commit()
        ids = {
            "tenant_a": tenant_a.id,
            "tenant_b": tenant_b.id,
            "location_a": location_a.id,
            "location_a2": location_a2.id,
            "location_b": location_b.id,
            "inactive": inactive.id,
            "table_a": table_a.id,
            "small_table": small_table.id,
            "table_a2": table_a2.id,
            "manager": manager_account.id,
        }

    bus = InMemoryEventBus()
    app = FastAPI()
    app.include_router(create_reservations_router(bus))
    actor: dict[str, CurrentStaff] = {"current": manager}

    def override_db() -> Generator[Session, None, None]:
        with TestingSession() as db:
            yield db

    def override_staff() -> CurrentStaff:
        return actor["current"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_staff] = override_staff

    with TestClient(app) as client:
        yield {
            "client": client,
            "Session": TestingSession,
            "bus": bus,
            "actor": actor,
            "principals": {
                "manager": manager,
                "waiter": waiter,
                "manager_a2": manager_a2,
                "foreign_manager": foreign_manager,
                "chef": chef,
            },
            "ids": ids,
        }
    Base.metadata.drop_all(engine)
    engine.dispose()


def reservation_request(ids: dict[str, str], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "customer_name": "Ada Diner",
        "customer_phone": "+234 801 234 5678",
        "location_id": ids["location_a"],
        "party_size": 4,
        "requested_at": future_at(18).isoformat(),
        "note": "Window table if possible",
    }
    payload.update(overrides)
    return payload


def create_public(harness: dict[str, object], **overrides: object) -> dict[str, object]:
    client = harness["client"]
    ids = harness["ids"]
    response = client.post("/api/v1/public/reservations", json=reservation_request(ids, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_public_request_validates_scope_time_hours_and_capacity(harness: dict[str, object]) -> None:
    client = harness["client"]
    ids = harness["ids"]

    valid = client.post("/api/v1/public/reservations", json=reservation_request(ids))
    assert valid.status_code == 201
    assert valid.json()["status"] == "REQUESTED"
    assert "customer_name" not in valid.json()
    assert "customer_phone" not in valid.json()
    assert "note" not in valid.json()
    assert len(valid.json()["access_token"]) >= 32

    local_nigerian = client.post(
        "/api/v1/public/reservations",
        json=reservation_request(ids, customer_phone="08012345678"),
    )
    assert local_nigerian.status_code == 201
    invalid_phone = client.post(
        "/api/v1/public/reservations",
        json=reservation_request(ids, customer_phone="0801234567"),
    )
    assert invalid_phone.status_code == 422
    assert "11-digit Nigerian" in invalid_phone.json()["detail"]

    naive = reservation_request(ids, requested_at=future_at(18).replace(tzinfo=None).isoformat())
    assert client.post("/api/v1/public/reservations", json=naive).status_code == 422
    past = reservation_request(ids, requested_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    assert client.post("/api/v1/public/reservations", json=past).status_code == 422
    outside_hours = reservation_request(ids, requested_at=future_at(3).isoformat())
    assert client.post("/api/v1/public/reservations", json=outside_hours).status_code == 422
    inactive = reservation_request(ids, location_id=ids["inactive"])
    assert client.post("/api/v1/public/reservations", json=inactive).status_code == 404
    foreign_table = reservation_request(ids, table_id=ids["table_a2"])
    assert client.post("/api/v1/public/reservations", json=foreign_table).status_code == 404
    too_small = reservation_request(ids, table_id=ids["small_table"])
    assert client.post("/api/v1/public/reservations", json=too_small).status_code == 422
    out_of_scope_features = reservation_request(ids, deposit=5000, waitlist=True)
    assert client.post("/api/v1/public/reservations", json=out_of_scope_features).status_code == 422


def test_public_status_requires_only_one_time_opaque_token_and_never_leaks_contact(
    harness: dict[str, object],
) -> None:
    created = create_public(harness)
    client = harness["client"]
    token = created["access_token"]

    # The creation response is the only response that contains the bearer
    # capability.  Its database representation is a non-reversible digest.
    assert created["access_token"] == token
    with harness["Session"]() as db:
        reservation = db.get(Reservation, created["id"])
        assert reservation is not None
        assert reservation.public_access_token_hash == sha256(token.encode("utf-8")).hexdigest()
        assert reservation.public_access_token_hash != token

    status = client.get(f"/api/v1/public/reservations/status/{token}")
    assert status.status_code == 200, status.text
    assert status.json()["id"] == created["id"]
    assert "access_token" not in status.json()
    assert "customer_name" not in status.json()
    assert "customer_phone" not in status.json()
    assert "note" not in status.json()

    # Neither a reservation ID nor phone number is a public lookup key.
    assert client.get(f"/api/v1/public/reservations/{created['id']}").status_code == 404
    assert client.get("/api/v1/public/reservations/status/+2348012345678").status_code == 404
    assert client.get("/api/v1/public/reservations/status/not-a-real-token").status_code == 404

    confirmed = client.post(
        f"/api/v1/staff/reservations/{created['id']}/confirm",
        json={"table_id": harness["ids"]["table_a"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert client.get(f"/api/v1/public/reservations/status/{token}").json()["status"] == "CONFIRMED"


def test_overlapping_requests_are_kept_for_human_review_and_customer_is_tenant_scoped(
    harness: dict[str, object],
) -> None:
    first = create_public(harness)
    second = create_public(harness)
    assert first["id"] != second["id"]
    SessionFactory = harness["Session"]
    ids = harness["ids"]
    with SessionFactory() as db:
        assert db.scalar(select(func.count(Reservation.id))) == 2
        customer = db.scalar(select(Customer).where(Customer.phone == "+2348012345678"))
        assert customer is not None
        visibilities = list(
            db.scalars(
                select(CustomerTenantRecord).where(
                    CustomerTenantRecord.customer_id == customer.id,
                    CustomerTenantRecord.tenant_id == ids["tenant_a"],
                )
            )
        )
        assert len(visibilities) == 1


def test_assigned_staff_queue_protects_contact_and_location_scope(harness: dict[str, object]) -> None:
    reservation = create_public(harness)
    client = harness["client"]
    ids = harness["ids"]
    actor = harness["actor"]
    principals = harness["principals"]

    actor["current"] = principals["waiter"]
    queue = client.get(f"/api/v1/staff/locations/{ids['location_a']}/reservations")
    assert queue.status_code == 200
    assert queue.json()[0]["contact"] == {"name": "Ada Diner", "phone": "+2348012345678"}

    actor["current"] = principals["manager_a2"]
    assert client.get(f"/api/v1/staff/reservations/{reservation['id']}").status_code == 404
    assert client.get(f"/api/v1/staff/locations/{ids['location_a']}/reservations").status_code == 404

    actor["current"] = principals["chef"]
    assert client.get(f"/api/v1/staff/locations/{ids['location_a']}/reservations").status_code == 403


def test_confirm_seat_status_machine_audit_and_live_events(harness: dict[str, object]) -> None:
    reservation = create_public(harness)
    client = harness["client"]
    ids = harness["ids"]

    confirmed = client.post(
        f"/api/v1/staff/reservations/{reservation['id']}/confirm",
        json={"table_id": ids["table_a"], "note": "Table checked by waiter"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"
    assert confirmed.json()["confirmed_by_id"] == ids["manager"]
    assert confirmed.json()["confirmed_at"]

    repeated = client.post(
        f"/api/v1/staff/reservations/{reservation['id']}/confirm",
        json={},
    )
    assert repeated.status_code == 409

    seated = client.post(
        f"/api/v1/staff/reservations/{reservation['id']}/seat",
        json={"note": "Party arrived"},
    )
    assert seated.status_code == 200, seated.text
    assert seated.json()["status"] == "SEATED"
    assert seated.json()["table_id"] == ids["table_a"]
    assert client.post(
        f"/api/v1/staff/reservations/{reservation['id']}/cancel",
        json={"reason": "Too late"},
    ).status_code == 409

    SessionFactory = harness["Session"]
    with SessionFactory() as db:
        audits = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.subject_id == reservation["id"])
                .order_by(AuditEvent.created_at)
            )
        )
        assert [row.event_type for row in audits] == ["RESERVATION_CONFIRMED", "RESERVATION_SEATED"]
        assert audits[0].actor_id == ids["manager"]
        assert audits[0].detail == "Table checked by waiter"
        assert audits[0].before_data["status"] == "REQUESTED"
        assert audits[0].after_data["table_id"] == ids["table_a"]
        assert audits[1].detail == "Party arrived"
        assert db.scalar(select(func.count(TableVisit.id))) == 0
        assert db.get(DiningTable, ids["table_a"]).is_active is False

    bus = harness["bus"]
    manager_events = asyncio.run(
        bus.replay(staff_channel(ids["tenant_a"], ids["location_a"], StaffRole.MANAGER.value), 0)
    )
    waiter_events = asyncio.run(
        bus.replay(staff_channel(ids["tenant_a"], ids["location_a"], StaffRole.WAITER.value), 0)
    )
    assert [event.payload["status"] for event in manager_events] == ["REQUESTED", "CONFIRMED", "SEATED"]
    assert len(waiter_events) == 3
    for event in manager_events + waiter_events:
        assert event.type.value == "reservation.changed"
        assert "customer_name" not in event.payload
        assert "customer_phone" not in event.payload
        assert "note" not in event.payload


def test_reject_cancel_and_required_seating_table(harness: dict[str, object]) -> None:
    rejected = create_public(harness, customer_phone="08010000001")
    cancelled = create_public(harness, customer_phone="08010000002")
    no_table = create_public(harness, customer_phone="08010000003")
    client = harness["client"]

    assert client.post(
        f"/api/v1/staff/reservations/{rejected['id']}/reject",
        json={"reason": "Private event"},
    ).json()["status"] == "REJECTED"
    assert client.post(
        f"/api/v1/staff/reservations/{cancelled['id']}/cancel",
        json={"reason": "Diner called"},
    ).json()["status"] == "CANCELLED"
    assert client.post(
        f"/api/v1/staff/reservations/{no_table['id']}/confirm",
        json={},
    ).status_code == 200
    missing_table = client.post(
        f"/api/v1/staff/reservations/{no_table['id']}/seat",
        json={},
    )
    assert missing_table.status_code == 422


def test_customer_can_edit_then_cancel_with_audit_and_policy_enforcement(
    harness: dict[str, object],
) -> None:
    reservation = create_public(harness)
    client = harness["client"]
    token = reservation["access_token"]

    # A material customer change deliberately returns the booking to review.
    updated = client.patch(
        f"/api/v1/public/reservations/status/{token}",
        json={"party_size": 6, "requested_at": future_at(19, days=3).isoformat()},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["party_size"] == 6
    assert updated.json()["status"] == "REQUESTED"

    cancelled = client.post(f"/api/v1/public/reservations/status/{token}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"

    with harness["Session"]() as db:
        events = list(
            db.scalars(
                select(AuditEvent.event_type)
                .where(AuditEvent.subject_id == reservation["id"])
                .order_by(AuditEvent.created_at)
            )
        )
        assert events == ["RESERVATION_CUSTOMER_UPDATED", "RESERVATION_CUSTOMER_CANCELLED"]
        location = db.get(Location, harness["ids"]["location_a"])
        assert location is not None
        location.customer_edits_enabled = False
        db.commit()

    rejected = client.patch(
        f"/api/v1/public/reservations/status/{token}",
        json={"party_size": 4, "requested_at": future_at(18, days=4).isoformat()},
    )
    assert rejected.status_code == 409


def test_qr_pass_check_in_requires_scoped_waiter_and_is_single_use(
    harness: dict[str, object],
) -> None:
    reservation = create_public(harness)
    client = harness["client"]
    token = reservation["access_token"]
    ids = harness["ids"]
    actor = harness["actor"]
    principals = harness["principals"]

    # Customer gets an opaque QR pass; it is not a reservation ID or phone number.
    issued = client.post(f"/api/v1/public/reservations/status/{token}/qr-pass")
    assert issued.status_code == 200, issued.text
    qr_pass = issued.json()["qr_pass_token"]
    assert len(qr_pass) >= 32

    # The reservation must be confirmed before any explicit check-in.
    assert client.post(
        f"/api/v1/staff/reservations/{reservation['id']}/confirm",
        json={"table_id": ids["table_a"]},
    ).status_code == 200

    # Same tenant but another assigned location, and another tenant, learn nothing.
    actor["current"] = principals["manager_a2"]
    assert client.get(f"/api/v1/staff/reservations/qr-pass/{qr_pass}").status_code == 404
    actor["current"] = principals["foreign_manager"]
    assert client.get(f"/api/v1/staff/reservations/qr-pass/{qr_pass}").status_code == 404

    actor["current"] = principals["waiter"]
    verified = client.get(f"/api/v1/staff/reservations/qr-pass/{qr_pass}")
    assert verified.status_code == 200, verified.text
    assert verified.json()["contact"]["phone"] == "+2348012345678"

    checked_in = client.post(f"/api/v1/staff/reservations/qr-pass/{qr_pass}/check-in")
    assert checked_in.status_code == 200, checked_in.text
    assert checked_in.json()["status"] == "CHECKED_IN"
    assert client.post(f"/api/v1/staff/reservations/qr-pass/{qr_pass}/check-in").status_code == 409

    with harness["Session"]() as db:
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.subject_id == reservation["id"],
                AuditEvent.event_type == "RESERVATION_CHECKED_IN",
            )
        )
        assert audit is not None
        assert audit.actor_id == principals["waiter"].staff_id
        persisted = db.get(Reservation, reservation["id"])
        assert persisted is not None
        assert persisted.checked_in_at is not None
        assert persisted.checked_in_by_id == principals["waiter"].staff_id


def test_overnight_operating_window_is_accepted() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionFactory() as db:
        tenant = Tenant(name="Overnight tenant")
        db.add(tenant)
        db.flush()
        location = Location(
            tenant_id=tenant.id,
            name="Night room",
            address="5 Night",
            timezone="Africa/Lagos",
        )
        db.add(location)
        db.flush()
        local_request = future_at(1, days=3)
        opening_date = local_request.date() - timedelta(days=1)
        db.add(
            OperatingHour(
                tenant_id=tenant.id,
                location_id=location.id,
                weekday=opening_date.weekday(),
                opens_at=time(18),
                closes_at=time(2),
                is_closed=False,
            )
        )
        db.commit()
        from app.reservation_service import validate_requested_time

        validate_requested_time(db, location, local_request)
    Base.metadata.drop_all(engine)
    engine.dispose()
