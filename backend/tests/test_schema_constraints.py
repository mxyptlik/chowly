from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    AuditEvent,
    Customer,
    CustomerTenantRecord,
    DiningTable,
    ItemRating,
    Location,
    MenuItem,
    Order,
    OrderLine,
    OrderRating,
    PaymentAttempt,
    StaffAccount,
    StaffLocationAssignment,
    Tenant,
)


NOW = datetime.now(timezone.utc)


@pytest.fixture()
def engine(tmp_path: Path) -> Engine:
    value = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    Base.metadata.create_all(value)
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture()
def seeded(engine: Engine) -> Engine:
    with engine.begin() as connection:
        connection.execute(Tenant.__table__.insert(), [
            {"id": "t1", "name": "Tenant One", "slug": "tenant-one"},
            {"id": "t2", "name": "Tenant Two", "slug": "tenant-two"},
        ])
        connection.execute(Location.__table__.insert(), [
            {"id": "l1", "tenant_id": "t1", "name": "One A", "slug": "one-a", "address": "Lagos"},
            {"id": "l3", "tenant_id": "t1", "name": "One B", "slug": "one-b", "address": "Abuja"},
            {"id": "l2", "tenant_id": "t2", "name": "Two A", "slug": "two-a", "address": "Kano"},
        ])
        connection.execute(Customer.__table__.insert(), {"id": "c1", "name": "Ada", "phone": "+2348000000001"})
        connection.execute(CustomerTenantRecord.__table__.insert(), {
            "id": "ctr1", "tenant_id": "t1", "customer_id": "c1",
            "name_snapshot": "Ada", "phone_snapshot": "+2348000000001",
        })
        connection.execute(DiningTable.__table__.insert(), [
            {"id": "d1", "tenant_id": "t1", "location_id": "l1", "label": "1", "capacity": 4},
            {"id": "d2", "tenant_id": "t2", "location_id": "l2", "label": "1", "capacity": 4},
        ])
        connection.execute(StaffAccount.__table__.insert(), {
            "id": "s1", "tenant_id": "t1", "name": "Waiter", "email": "waiter@example.test",
        })
        connection.execute(StaffLocationAssignment.__table__.insert(), {
            "id": "sla1", "tenant_id": "t1", "location_id": "l1", "staff_id": "s1",
        })
        connection.execute(MenuItem.__table__.insert(), {
            "id": "m1", "tenant_id": "t1", "location_id": "l1", "name": "Jollof",
            "category": "Mains", "item_type": "FOOD", "base_price": Decimal("1000"),
        })
        connection.execute(Order.__table__.insert(), {
            "id": "o1", "tenant_id": "t1", "location_id": "l1", "table_id": "d1",
            "customer_id": "c1", "customer_tenant_record_id": "ctr1", "public_access_token_hash": "a" * 64,
        })
        connection.execute(OrderLine.__table__.insert(), {
            "id": "ol1", "tenant_id": "t1", "location_id": "l1", "order_id": "o1",
            "menu_item_id": "m1", "quantity": 1, "item_name_snapshot": "Jollof",
            "queue_destination": "KITCHEN", "unit_price": Decimal("1000"),
        })
    return engine


def test_initial_migration_upgrades_empty_database_and_downgrades(tmp_path: Path) -> None:
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["CHOWLY_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "upgrade", "head"],
        cwd=backend,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert upgrade.returncode == 0, upgrade.stderr
    migrated = create_engine(f"sqlite:///{database}")
    assert set(Base.metadata.tables).issubset(inspect(migrated).get_table_names())
    migrated.dispose()
    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "downgrade", "base"],
        cwd=backend,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert downgrade.returncode == 0, downgrade.stderr


def test_tenant_retention_default_and_extension_constraint(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(Tenant.__table__.insert(), {"id": "default", "name": "Default", "slug": "default"})
        assert connection.scalar(text("SELECT retention_days FROM tenants WHERE id='default'")) == 90
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(Tenant.__table__.insert(), {"id": "bad", "name": "Bad", "slug": "bad", "retention_days": 121})
    tenant = Tenant(name="Configured")
    tenant.configure_retention(120)
    assert tenant.retention_days == 120
    with pytest.raises(ValueError):
        tenant.configure_retention(121)
    tenant.configure_retention(180, approved_by="platform-admin")
    assert tenant.retention_extension_approved_by == "platform-admin"


def test_cross_tenant_and_cross_location_links_are_rejected(seeded: Engine) -> None:
    with pytest.raises(IntegrityError), seeded.begin() as connection:
        connection.execute(DiningTable.__table__.insert(), {
            "id": "wrong-table", "tenant_id": "t1", "location_id": "l2", "label": "x", "capacity": 2,
        })
    with pytest.raises(IntegrityError), seeded.begin() as connection:
        connection.execute(StaffLocationAssignment.__table__.insert(), {
            "id": "wrong-assignment", "tenant_id": "t2", "location_id": "l2", "staff_id": "s1",
        })
    with pytest.raises(IntegrityError), seeded.begin() as connection:
        connection.execute(Order.__table__.insert(), {
            "id": "wrong-order", "tenant_id": "t1", "location_id": "l3", "table_id": "d1",
            "customer_id": "c1", "customer_tenant_record_id": "ctr1", "public_access_token_hash": "b" * 64,
        })


def test_duplicate_item_and_order_ratings_are_rejected(seeded: Engine) -> None:
    with seeded.begin() as connection:
        connection.execute(ItemRating.__table__.insert(), {
            "id": "ir1", "tenant_id": "t1", "location_id": "l1", "order_id": "o1",
            "order_line_id": "ol1", "customer_id": "c1", "score": 5,
        })
    with pytest.raises(IntegrityError), seeded.begin() as connection:
        connection.execute(ItemRating.__table__.insert(), {
            "id": "ir2", "tenant_id": "t1", "location_id": "l1", "order_id": "o1",
            "order_line_id": "ol1", "customer_id": "c1", "score": 4,
        })
    with seeded.begin() as connection:
        connection.execute(OrderRating.__table__.insert(), {
            "id": "or1", "tenant_id": "t1", "location_id": "l1", "order_id": "o1",
            "customer_id": "c1", "score": 5,
        })
    with pytest.raises(IntegrityError), seeded.begin() as connection:
        connection.execute(OrderRating.__table__.insert(), {
            "id": "or2", "tenant_id": "t1", "location_id": "l1", "order_id": "o1",
            "customer_id": "c1", "score": 3,
        })


def test_failed_payment_retries_but_only_one_success_is_allowed(seeded: Engine) -> None:
    with seeded.begin() as connection:
        connection.execute(PaymentAttempt.__table__.insert(), [
            {"id": "p1", "tenant_id": "t1", "location_id": "l1", "order_id": "o1", "method": "CARD", "amount": Decimal("1000"), "status": "FAILED", "reference": "R1", "idempotency_key": "I1"},
            {"id": "p2", "tenant_id": "t1", "location_id": "l1", "order_id": "o1", "method": "CARD", "amount": Decimal("1000"), "status": "FAILED", "reference": "R2", "idempotency_key": "I2"},
            {"id": "p3", "tenant_id": "t1", "location_id": "l1", "order_id": "o1", "method": "TRANSFER", "amount": Decimal("1000"), "status": "SUCCESSFUL", "reference": "R3", "idempotency_key": "I3"},
        ])
    with pytest.raises(IntegrityError), seeded.begin() as connection:
        connection.execute(PaymentAttempt.__table__.insert(), {
            "id": "p4", "tenant_id": "t1", "location_id": "l1", "order_id": "o1",
            "method": "WALLET", "amount": Decimal("1000"), "status": "SUCCESSFUL",
            "reference": "R4", "idempotency_key": "I4",
        })


def test_invalid_enum_status_is_rejected(seeded: Engine) -> None:
    with pytest.raises(IntegrityError), seeded.begin() as connection:
        connection.execute(text("UPDATE orders SET status='NOT_A_STATUS' WHERE id='o1'"))


def test_audit_events_are_append_only_in_orm_service_behavior(seeded: Engine) -> None:
    with Session(seeded) as session:
        event = AuditEvent(
            id="a1", tenant_id="t1", location_id="l1", actor_id="s1",
            event_type="ORDER_ACCEPTED", subject_type="ORDER", subject_id="o1",
        )
        session.add(event)
        session.commit()
        event.detail = "changed"
        with pytest.raises(ValueError, match="append-only"):
            session.commit()
        session.rollback()
        session.delete(event)
        with pytest.raises(ValueError, match="append-only"):
            session.commit()
