"""FastAPI route modules."""
from app.routers.auth import router as auth_router
from app.routers.locations import router as locations_router
from app.routers.menu import router as menu_router
from app.routers.payments import router as payments_router
from app.routers.platform_admin import router as platform_admin_router
from app.routers.prep import router as prep_router
from app.routers.public_orders import router as public_orders_router
from app.routers.realtime import router as realtime_router
from app.routers.reports import router as reports_router
from app.routers.reservations import router as reservations_router
from app.routers.feedback import router as feedback_router
from app.routers.retention import router as retention_router
from app.routers.staff_orders import router as staff_orders_router
from app.routers.tables import router as tables_router

__all__ = [
    "auth_router",
    "locations_router",
    "menu_router",
    "payments_router",
    "platform_admin_router",
    "prep_router",
    "public_orders_router",
    "realtime_router",
    "reports_router",
    "reservations_router",
    "feedback_router",
    "retention_router",
    "staff_orders_router",
    "tables_router",
]
