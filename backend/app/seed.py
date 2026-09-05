"""Development-only deterministic seven-tenant pilot fixtures.

This is intentionally not a provisioning path: production startup does not call
it, and it returns without changing a non-empty database. The seed data exists
only to make local verification repeatable.
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import DiningTable, InvitationStatus, Location, MenuCategory, MenuItem, MenuItemType, ModifierGroup, ModifierOption, OperatingHour, QueueDestination, StaffAccount, StaffLocationAssignment, StaffRole, StaffRoleAssignment, Tenant
from app.qr_service import issue_table_qr


DEMO_PASSWORD = "ChowlyDemo!2026"
PILOT_TENANTS: tuple[tuple[str, str], ...] = (
    ("Mango & Ash Hospitality", "Victoria Island"),
    ("Buka Seven Hospitality", "Lekki"),
    ("Cedar Spoon Hospitality", "Ikeja"),
    ("Dawn Coast Hospitality", "Yaba"),
    ("Ember Kitchen Hospitality", "Surulere"),
    ("Fifth Palm Hospitality", "Ikoyi"),
    ("Golden Bowl Hospitality", "Wuse II"),
)


def _ensure_pilot_staff(
    db: Session,
    *,
    tenant: Tenant,
    location: Location,
    ordinal: int,
    password_hash: str,
    accepted_at: datetime,
) -> None:
    """Repair pilot logins without replacing an existing local demo location."""

    for label, role in (
        ("Owner", StaffRole.TENANT_OWNER),
        ("Manager", StaffRole.MANAGER),
        ("Waiter", StaffRole.WAITER),
        ("Chef", StaffRole.CHEF),
        ("Bartender", StaffRole.BARTENDER),
    ):
        email = f"pilot{ordinal}.{role.value.lower()}@demo.chowly.ng"
        account = db.scalar(select(StaffAccount).where(StaffAccount.email == email))
        if account is None:
            account = StaffAccount(
                tenant_id=tenant.id,
                name=f"Pilot {ordinal} {label}",
                email=email,
                password_hash=password_hash,
                invitation_status=InvitationStatus.ACCEPTED,
                accepted_at=accepted_at,
                is_active=True,
                location_id=location.id,
                role=role.value,
            )
            db.add(account)
            db.flush()
        if db.scalar(
            select(StaffRoleAssignment.id).where(
                StaffRoleAssignment.tenant_id == tenant.id,
                StaffRoleAssignment.staff_id == account.id,
                StaffRoleAssignment.role == role,
            )
        ) is None:
            db.add(StaffRoleAssignment(tenant_id=tenant.id, staff_id=account.id, role=role))
        if db.scalar(
            select(StaffLocationAssignment.id).where(
                StaffLocationAssignment.tenant_id == tenant.id,
                StaffLocationAssignment.location_id == location.id,
                StaffLocationAssignment.staff_id == account.id,
            )
        ) is None:
            db.add(StaffLocationAssignment(tenant_id=tenant.id, location_id=location.id, staff_id=account.id))


def seed(db: Session) -> None:
    """Create exactly seven isolated demo tenants in an empty dev database."""
    settings = get_settings()
    if not settings.is_development:
        return
    password_hash = hash_password(DEMO_PASSWORD)
    accepted_at = datetime.now(UTC)
    if not db.scalar(select(StaffAccount.id).where(StaffAccount.email == "platform.admin@demo.chowly.ng")):
        db.add(StaffAccount(
            name="Chowly Platform Administrator",
            email="platform.admin@demo.chowly.ng",
            password_hash=password_hash,
            invitation_status=InvitationStatus.ACCEPTED,
            accepted_at=accepted_at,
            is_platform_admin=True,
            is_active=True,
            role=StaffRole.PLATFORM_ADMIN.value,
        ))
    for ordinal, (tenant_name, district) in enumerate(PILOT_TENANTS, start=1):
        tenant = db.scalar(select(Tenant).where(Tenant.name == tenant_name))
        if tenant is None:
            tenant = Tenant(name=tenant_name)
            db.add(tenant)
            db.flush()
        # Legacy development databases may contain a tenant and location but
        # lack its service schedule. Repair that safely so the public demo can
        # actually accept reservations after an upgrade.
        existing_location = db.scalar(select(Location).where(Location.tenant_id == tenant.id))
        if existing_location is not None:
            has_hours = db.scalar(
                select(OperatingHour.id).where(OperatingHour.location_id == existing_location.id)
            )
            if has_hours is None:
                db.add_all(
                    OperatingHour(
                        tenant_id=tenant.id,
                        location_id=existing_location.id,
                        weekday=weekday,
                        opens_at=time(9),
                        closes_at=time(22),
                        is_closed=False,
                    )
                    for weekday in range(7)
                )
            _ensure_pilot_staff(
                db,
                tenant=tenant,
                location=existing_location,
                ordinal=ordinal,
                password_hash=password_hash,
                accepted_at=accepted_at,
            )
            continue
        location = Location(tenant_id=tenant.id, name=f"{tenant_name.removesuffix(' Hospitality')} — {district}", address=f"{ordinal} Pilot Service Road, {district}, Nigeria", vat_rate=Decimal("0.075"), service_charge_rate=Decimal("0.000"))
        db.add(location)
        db.flush()
        db.add_all(
            OperatingHour(
                tenant_id=tenant.id,
                location_id=location.id,
                weekday=weekday,
                opens_at=time(9),
                closes_at=time(22),
                is_closed=False,
            )
            for weekday in range(7)
        )
        tables = [DiningTable(tenant_id=tenant.id, location_id=location.id, label=f"Table {number:02d}", capacity=4, daily_code=f"PILOT-{ordinal:02d}-T{number:02d}", code_issued_on=date.today().isoformat()) for number in range(1, 4)]
        db.add_all(tables)
        _ensure_pilot_staff(
            db,
            tenant=tenant,
            location=location,
            ordinal=ordinal,
            password_hash=password_hash,
            accepted_at=accepted_at,
        )
        grill = MenuCategory(tenant_id=tenant.id, location_id=location.id, name="From the grill", sort_order=10)
        drinks = MenuCategory(tenant_id=tenant.id, location_id=location.id, name="Cold bar", sort_order=20)
        db.add_all([grill, drinks])
        db.flush()
        suya = MenuItem(tenant_id=tenant.id, location_id=location.id, category_id=grill.id, name="Yaji Chicken Suya", description="Charred chicken thigh, yaji spice, onions and tomato.", category="From the grill", item_type=MenuItemType.FOOD, queue_destination=QueueDestination.KITCHEN, base_price=Decimal("6200"))
        zobo = MenuItem(tenant_id=tenant.id, location_id=location.id, category_id=drinks.id, name="Hibiscus Zobo Fizz", description="Cold-brewed hibiscus, ginger and citrus.", category="Cold bar", item_type=MenuItemType.DRINK, queue_destination=QueueDestination.BAR, base_price=Decimal("2200"))
        db.add_all([suya, zobo])
        db.flush()
        extras = ModifierGroup(tenant_id=tenant.id, location_id=location.id, menu_item_id=suya.id, name="Extras", minimum_selections=0, maximum_selections=2)
        sweetness = ModifierGroup(tenant_id=tenant.id, location_id=location.id, menu_item_id=zobo.id, name="Sweetness", minimum_selections=0, maximum_selections=1)
        db.add_all([extras, sweetness])
        db.flush()
        db.add_all([ModifierOption(tenant_id=tenant.id, location_id=location.id, menu_item_id=suya.id, group_id=extras.id, name="Extra chicken", price_delta=Decimal("1800")), ModifierOption(tenant_id=tenant.id, location_id=location.id, menu_item_id=zobo.id, group_id=sweetness.id, name="Less sweet", price_delta=Decimal("0"))])
        db.flush()
        for table in tables:
            issue_table_qr(db, table=table, location=location, secret=settings.realtime_signing_secret)
    db.commit()
