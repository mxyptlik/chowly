"""Chowly API application composition.

Domain behavior lives in scoped routers and services. This module deliberately
contains no caller-supplied staff authority or duplicate legacy order handlers.
"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db import SessionLocal
from app.routers.auth import router as auth_router
from app.routers.feedback import router as feedback_router
from app.routers.locations import router as locations_router
from app.routers.menu import router as menu_router
from app.routers.payments import router as payments_router
from app.routers.platform_admin import router as platform_admin_router
from app.routers.prep import router as prep_router
from app.routers.public_orders import router as public_orders_router
from app.routers.public_restaurants import router as public_restaurants_router
from app.routers.onboarding import router as onboarding_router
from app.routers.realtime import router as realtime_router
from app.routers.reports import router as reports_router
from app.routers.reservations import router as reservations_router
from app.routers.retention import router as retention_router
from app.routers.staff_orders import router as staff_orders_router
from app.routers.tables import router as tables_router
from app.seed import seed
from app.qr_service import ensure_daily_table_qrs


settings = get_settings()
logger = logging.getLogger("chowly.startup")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Alembic owns runtime schema creation. Local/test startup only seeds the
    # already-migrated database; production seeding is a deliberate no-op.
    with SessionLocal() as db:
        seed(db)
        # Restart-safe daily QR provisioning. Existing valid daily QR codes are
        # retained; only missing codes are issued.
        created_qrs, existing_qrs = ensure_daily_table_qrs(
            db, secret=settings.session_signing_secret
        )
        db.commit()
        db.execute(text("SELECT 1"))
    logger.info(
        "startup_ready",
        extra={
            "event": "startup_ready",
            "database": "connected",
            "daily_qrs_created": created_qrs,
            "daily_qrs_existing": existing_qrs,
            "application": "ready",
        },
    )
    yield


app = FastAPI(title="Chowly API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    auth_router,
    realtime_router,
    locations_router,
    menu_router,
    tables_router,
    reservations_router,
    feedback_router,
    retention_router,
    reports_router,
    public_orders_router,
    public_restaurants_router,
    onboarding_router,
    payments_router,
    platform_admin_router,
    staff_orders_router,
    prep_router,
):
    app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    """Readiness, not merely process liveness: API needs both durable stores."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database or redis is unavailable") from exc
    return {"status": "ok", "database": "ok", "redis": "ok"}
