"""Release-proof checks that exercise system wiring without browser ownership."""

from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db import Base
from app.models import DiningTable, Location, MenuItem, ModifierOption, StaffAccount, TableQrToken, Tenant
from app.seed import PILOT_TENANTS, seed


def test_development_seed_has_seven_isolated_complete_pilot_tenants(monkeypatch) -> None:
    """Every pilot has its own complete operational fixture and QR boundaries."""
    monkeypatch.setenv("CHOWLY_ENVIRONMENT", "development")
    monkeypatch.setenv("CHOWLY_DATABASE_URL", "sqlite://")
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            from sqlalchemy.orm import Session
            session = Session(bind=connection)
            seed(session)
            assert session.scalar(select(func.count()).select_from(Tenant)) == 7
            assert session.scalar(select(func.count()).select_from(Location)) == 7
            assert session.scalar(select(func.count()).select_from(DiningTable)) == 21
            assert session.scalar(select(func.count()).select_from(StaffAccount)) == 36
            assert session.scalar(select(func.count()).select_from(MenuItem)) == 14
            assert session.scalar(select(func.count()).select_from(ModifierOption)) == 14
            assert session.scalar(select(func.count()).select_from(TableQrToken)) == 21
            # A tenant sees no accidental staff/table projection from another.
            for tenant in session.scalars(select(Tenant)).all():
                assert session.scalar(select(func.count()).select_from(Location).where(Location.tenant_id == tenant.id)) == 1
                assert session.scalar(select(func.count()).select_from(StaffAccount).where(StaffAccount.tenant_id == tenant.id)) == 5
                assert session.scalar(select(func.count()).select_from(DiningTable).where(DiningTable.tenant_id == tenant.id)) == 3
            seed(session)
            assert session.scalar(select(func.count()).select_from(Tenant)) == len(PILOT_TENANTS)
            session.close()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
        get_settings.cache_clear()


def test_runtime_does_not_call_create_all() -> None:
    """Alembic is the only production schema creator; tests may use metadata."""
    source = ("backend/app/main.py")
    from pathlib import Path
    contents = Path(source).read_text(encoding="utf-8")
    assert "create_all" not in contents


def test_compose_declares_migration_and_service_readiness() -> None:
    from pathlib import Path
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "alembic upgrade head" in compose
    assert compose.count("healthcheck:") >= 5
    assert "condition: service_healthy" in compose
