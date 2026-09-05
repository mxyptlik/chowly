from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def uid() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def opaque_token_hash() -> str:
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def enum_column(enum: type[StrEnum], name: str) -> SAEnum:
    """Portable constrained enums with stable API-facing stored values."""
    return SAEnum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [value.value for value in values],
    )


class ServiceMode(StrEnum):
    DINE_IN = "DINE_IN"
    TAKEAWAY = "TAKEAWAY"


class OrderSource(StrEnum):
    QR = "QR"
    MANUAL = "MANUAL"


class OrderStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    PREPARING = "PREPARING"
    READY = "READY_FOR_SERVICE"
    SERVED = "SERVED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class LineStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    READY = "READY"
    CANCELLED = "CANCELLED"


class QueueDestination(StrEnum):
    KITCHEN = "KITCHEN"
    BAR = "BAR"


class MenuItemType(StrEnum):
    FOOD = "FOOD"
    DRINK = "DRINK"


class StaffRole(StrEnum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    TENANT_OWNER = "TENANT_OWNER"
    MANAGER = "MANAGER"
    WAITER = "WAITER"
    CHEF = "CHEF"
    BARTENDER = "BARTENDER"


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PaymentMethod(StrEnum):
    CARD = "CARD"
    TRANSFER = "TRANSFER"
    WALLET = "WALLET"
    CASH = "CASH"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"


class RefundStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"


class ReceiptDeliveryStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class ReservationStatus(StrEnum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CHECKED_IN = "CHECKED_IN"
    SEATED = "SEATED"


class ComplaintStatus(StrEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class TenantLifecycle(StrEnum):
    """Whether a restaurant may be shown on Chowly's public surfaces."""

    PENDING_SETUP = "PENDING_SETUP"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
        CheckConstraint("retention_days >= 1", name="ck_tenant_retention_positive"),
        CheckConstraint(
            "retention_days <= 120 OR retention_extension_approved_at IS NOT NULL",
            name="ck_tenant_retention_extension_approved",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    # Public identifiers are deliberately not an authority boundary.  They are
    # immutable once issued so links shared by a restaurant remain stable.
    slug: Mapped[str] = mapped_column(String(180), index=True)
    lifecycle: Mapped[TenantLifecycle] = mapped_column(
        enum_column(TenantLifecycle, "tenant_lifecycle"),
        default=TenantLifecycle.ACTIVE,
        server_default=TenantLifecycle.ACTIVE.value,
    )
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    cover_image_url: Mapped[str | None] = mapped_column(String(1000))
    retention_days: Mapped[int] = mapped_column(Integer, default=90, server_default="90")
    retention_extension_requested_days: Mapped[int | None] = mapped_column(Integer)
    retention_extension_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_extension_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_extension_approved_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    locations: Mapped[list[Location]] = relationship(back_populates="tenant")

    def configure_retention(self, days: int, *, approved_by: str | None = None) -> None:
        """Apply the V1 1-120 day policy, with explicit platform approval above it."""
        if days < 1:
            raise ValueError("Retention must be at least one day.")
        if days > 120 and not approved_by:
            raise ValueError("Retention above 120 days requires platform approval.")
        self.retention_days = days
        if days > 120:
            self.retention_extension_approved_by = approved_by
            self.retention_extension_approved_at = utc_now()


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_location_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_location_tenant_name"),
        UniqueConstraint("tenant_id", "slug", name="uq_location_tenant_slug"),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 1", name="ck_location_vat_rate"),
        CheckConstraint("service_charge_rate >= 0 AND service_charge_rate <= 1", name="ck_location_service_charge_rate"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(180), index=True)
    address: Mapped[str] = mapped_column(String(300))
    cover_image_url: Mapped[str | None] = mapped_column(String(1000))
    currency: Mapped[str] = mapped_column(String(3), default="NGN", server_default="NGN")
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6), default=Decimal("0.075"), server_default="0.075")
    service_charge_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6), default=Decimal("0"), server_default="0")
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Lagos", server_default="Africa/Lagos")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    customer_edits_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    customer_edit_cutoff_minutes: Mapped[int] = mapped_column(Integer, default=120, server_default="120")
    customer_cancellations_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    customer_cancellation_cutoff_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    tenant: Mapped[Tenant] = relationship(back_populates="locations")
    tables: Mapped[list[DiningTable]] = relationship(back_populates="location")
    # Read-only projection; MenuCategory owns the writable composite item scope.
    menu_items: Mapped[list[MenuItem]] = relationship(viewonly=True)
    menu_categories: Mapped[list[MenuCategory]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )
    operating_hours: Mapped[list[OperatingHour]] = relationship(back_populates="location", cascade="all, delete-orphan")


def _fallback_slug(value: str) -> str:
    """Keep legacy/internal model construction valid; public flows de-duplicate."""
    import re
    return (re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "restaurant")[:160]


@event.listens_for(Tenant, "before_insert")
def _tenant_slug_before_insert(_: object, __: object, target: Tenant) -> None:
    if not target.slug:
        target.slug = _fallback_slug(target.name)


@event.listens_for(Location, "before_insert")
def _location_slug_before_insert(_: object, __: object, target: Location) -> None:
    if not target.slug:
        target.slug = _fallback_slug(target.name)


class OperatingHour(Base):
    __tablename__ = "operating_hours"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], name="fk_operating_hour_location", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "location_id", "weekday", name="uq_operating_hour_day"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_operating_hour_weekday"),
        CheckConstraint("is_closed = true OR (opens_at IS NOT NULL AND closes_at IS NOT NULL)", name="ck_operating_hour_times_when_open"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    weekday: Mapped[int] = mapped_column(Integer)
    opens_at: Mapped[time | None] = mapped_column(Time)
    closes_at: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    location: Mapped[Location] = relationship(back_populates="operating_hours", overlaps="tenant")


class StaffAccount(Base):
    __tablename__ = "staff_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_staff_account_tenant_id"),
        UniqueConstraint("email", name="uq_staff_account_email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    invitation_status: Mapped[InvitationStatus] = mapped_column(enum_column(InvitationStatus, "invitation_status"), default=InvitationStatus.PENDING, server_default=InvitationStatus.PENDING.value)
    invitation_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    invitation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by_id: Mapped[str | None] = mapped_column(ForeignKey("staff_accounts.id", ondelete="SET NULL"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    # Transitional prototype projection. P02 moves callers to normalized assignments.
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), index=True)
    role: Mapped[str | None] = mapped_column(String(30))
    role_assignments: Mapped[list[StaffRoleAssignment]] = relationship(back_populates="staff", cascade="all, delete-orphan", foreign_keys="StaffRoleAssignment.staff_id")
    location_assignments: Mapped[list[StaffLocationAssignment]] = relationship(back_populates="staff", cascade="all, delete-orphan", foreign_keys="StaffLocationAssignment.staff_id")


class StaffRoleAssignment(Base):
    __tablename__ = "staff_role_assignments"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "staff_id"], ["staff_accounts.tenant_id", "staff_accounts.id"], name="fk_staff_role_account", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "staff_id", "role", name="uq_staff_role"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    staff_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[StaffRole] = mapped_column(enum_column(StaffRole, "staff_role"))
    granted_by_id: Mapped[str | None] = mapped_column(ForeignKey("staff_accounts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    staff: Mapped[StaffAccount] = relationship(back_populates="role_assignments", foreign_keys=[staff_id])


class StaffLocationAssignment(Base):
    __tablename__ = "staff_location_assignments"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "staff_id"], ["staff_accounts.tenant_id", "staff_accounts.id"], name="fk_staff_location_account", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], name="fk_staff_location_location", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "location_id", "staff_id", name="uq_staff_location"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    staff_id: Mapped[str] = mapped_column(String(36))
    assigned_by_id: Mapped[str | None] = mapped_column(ForeignKey("staff_accounts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    staff: Mapped[StaffAccount] = relationship(back_populates="location_assignments", foreign_keys=[staff_id])


Staff = StaffAccount  # compatibility alias; canonical name is StaffAccount


class DiningTable(Base):
    __tablename__ = "dining_tables"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], name="fk_dining_table_location", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "location_id", "id", name="uq_dining_table_scope_id"),
        UniqueConstraint("tenant_id", "location_id", "label", name="uq_dining_table_label"),
        CheckConstraint("capacity > 0", name="ck_dining_table_capacity"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36), index=True)
    label: Mapped[str] = mapped_column(String(30))
    capacity: Mapped[int] = mapped_column(Integer)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    # Deprecated projection retained until P04 moves QR callers to TableQrToken.
    daily_code: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    code_issued_on: Mapped[str | None] = mapped_column(String(10))
    location: Mapped[Location] = relationship(back_populates="tables", overlaps="tenant")
    visits: Mapped[list[TableVisit]] = relationship(back_populates="table")
    qr_tokens: Mapped[list[TableQrToken]] = relationship(back_populates="table", cascade="all, delete-orphan")


class TableQrToken(Base):
    __tablename__ = "table_qr_tokens"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "table_id"], ["dining_tables.tenant_id", "dining_tables.location_id", "dining_tables.id"], name="fk_table_qr_table", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id", "generated_by_id"], ["staff_location_assignments.tenant_id", "staff_location_assignments.location_id", "staff_location_assignments.staff_id"], name="fk_table_qr_generator_assignment"),
        Index("ix_table_qr_daily_lookup", "tenant_id", "location_id", "table_id", "issued_on"),
        Index("uq_table_qr_active_daily", "tenant_id", "location_id", "table_id", "issued_on", unique=True, postgresql_where=text("invalidated_at IS NULL"), sqlite_where=text("invalidated_at IS NULL")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    table_id: Mapped[str] = mapped_column(String(36))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    issued_on: Mapped[date] = mapped_column(Date, default=date.today)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_by_id: Mapped[str | None] = mapped_column(String(36))
    table: Mapped[DiningTable] = relationship(back_populates="qr_tokens", overlaps="location,tenant")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CustomerTenantRecord(Base):
    __tablename__ = "customer_tenant_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", name="uq_customer_tenant_visibility"),
        UniqueConstraint("tenant_id", "id", name="uq_customer_tenant_record_scope_id"),
        UniqueConstraint("tenant_id", "customer_id", "id", name="uq_customer_tenant_record_customer_scope"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    name_snapshot: Mapped[str] = mapped_column(String(160))
    phone_snapshot: Mapped[str] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TableVisit(Base):
    __tablename__ = "table_visits"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "table_id"], ["dining_tables.tenant_id", "dining_tables.location_id", "dining_tables.id"], name="fk_table_visit_table", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "location_id", "id", name="uq_table_visit_scope_id"),
        Index("uq_table_visit_active", "tenant_id", "location_id", "table_id", unique=True, postgresql_where=text("closed_at IS NULL"), sqlite_where=text("closed_at IS NULL")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    table_id: Mapped[str] = mapped_column(String(36), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_by_order_id: Mapped[str | None] = mapped_column(String(36))
    closed_by_id: Mapped[str | None] = mapped_column(ForeignKey("staff_accounts.id", ondelete="SET NULL"))
    table: Mapped[DiningTable] = relationship(back_populates="visits", overlaps="location,tenant")


class MenuCategory(Base):
    __tablename__ = "menu_categories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_menu_category_location",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "location_id", "id", name="uq_menu_category_scope_id"),
        UniqueConstraint("tenant_id", "location_id", "name", name="uq_menu_category_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    location: Mapped[Location] = relationship(back_populates="menu_categories", overlaps="tenant")
    items: Mapped[list[MenuItem]] = relationship(back_populates="menu_category")


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], name="fk_menu_item_location", ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "location_id", "category_id"],
            ["menu_categories.tenant_id", "menu_categories.location_id", "menu_categories.id"],
            name="fk_menu_item_category",
        ),
        UniqueConstraint("tenant_id", "location_id", "id", name="uq_menu_item_scope_id"),
        CheckConstraint("base_price >= 0", name="ck_menu_item_price_nonnegative"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    image_url: Mapped[str | None] = mapped_column(String(1000))
    # Nullable only for direct legacy/P01 fixture compatibility. The canonical
    # Alembic schema is NOT NULL and every P04 write validates scoped ownership.
    category_id: Mapped[str | None] = mapped_column(String(36), index=True)
    # Human-readable compatibility snapshot retained for legacy order/menu clients.
    category: Mapped[str] = mapped_column(String(80))
    item_type: Mapped[MenuItemType] = mapped_column(enum_column(MenuItemType, "menu_item_type"))
    queue_destination: Mapped[QueueDestination] = mapped_column(
        enum_column(QueueDestination, "menu_queue_destination"),
        default=QueueDestination.KITCHEN,
        server_default=QueueDestination.KITCHEN.value,
    )
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    available: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    sold_out_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sold_out_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    location: Mapped[Location] = relationship(viewonly=True)
    menu_category: Mapped[MenuCategory | None] = relationship(back_populates="items", overlaps="location,tenant")
    modifiers: Mapped[list[ModifierOption]] = relationship(back_populates="menu_item", cascade="all, delete-orphan")
    modifier_groups: Mapped[list[ModifierGroup]] = relationship(back_populates="menu_item", cascade="all, delete-orphan")


class ModifierGroup(Base):
    __tablename__ = "modifier_groups"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "menu_item_id"], ["menu_items.tenant_id", "menu_items.location_id", "menu_items.id"], name="fk_modifier_group_menu_item", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "location_id", "menu_item_id", "name", name="uq_modifier_group_name"),
        CheckConstraint("minimum_selections >= 0", name="ck_modifier_group_min"),
        CheckConstraint("maximum_selections >= minimum_selections", name="ck_modifier_group_max"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    menu_item_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100))
    minimum_selections: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    maximum_selections: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    menu_item: Mapped[MenuItem] = relationship(back_populates="modifier_groups", overlaps="location,tenant")
    options: Mapped[list[ModifierOption]] = relationship(back_populates="group")


class ModifierOption(Base):
    __tablename__ = "modifier_options"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "menu_item_id"], ["menu_items.tenant_id", "menu_items.location_id", "menu_items.id"], name="fk_modifier_option_menu_item", ondelete="CASCADE"),
        CheckConstraint("price_delta >= 0", name="ck_modifier_option_price_nonnegative"),
        UniqueConstraint("tenant_id", "location_id", "menu_item_id", "id", name="uq_modifier_option_scope_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    menu_item_id: Mapped[str] = mapped_column(String(36), index=True)
    group_id: Mapped[str | None] = mapped_column(ForeignKey("modifier_groups.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    price_delta: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    available: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    menu_item: Mapped[MenuItem] = relationship(back_populates="modifiers", overlaps="location,tenant")
    group: Mapped[ModifierGroup | None] = relationship(back_populates="options")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], name="fk_order_location"),
        ForeignKeyConstraint(["tenant_id", "location_id", "table_id"], ["dining_tables.tenant_id", "dining_tables.location_id", "dining_tables.id"], name="fk_order_table"),
        ForeignKeyConstraint(["tenant_id", "location_id", "visit_id"], ["table_visits.tenant_id", "table_visits.location_id", "table_visits.id"], name="fk_order_visit"),
        ForeignKeyConstraint(["tenant_id", "customer_id", "customer_tenant_record_id"], ["customer_tenant_records.tenant_id", "customer_tenant_records.customer_id", "customer_tenant_records.id"], name="fk_order_customer_tenant_record"),
        ForeignKeyConstraint(["tenant_id", "location_id", "owner_id"], ["staff_location_assignments.tenant_id", "staff_location_assignments.location_id", "staff_location_assignments.staff_id"], name="fk_order_owner_assignment"),
        UniqueConstraint("tenant_id", "location_id", "id", name="uq_order_scope_id"),
        CheckConstraint("estimated_wait_minutes IS NULL OR estimated_wait_minutes BETWEEN 1 AND 180", name="ck_order_wait_minutes"),
        CheckConstraint("subtotal_amount >= 0 AND vat_amount >= 0 AND service_charge_amount >= 0 AND total_amount >= 0", name="ck_order_amounts_nonnegative"),
        Index("ix_order_active_table", "tenant_id", "location_id", "table_id", "status"),
        Index("ix_order_report_created", "tenant_id", "location_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36), index=True)
    table_id: Mapped[str | None] = mapped_column(String(36))
    visit_id: Mapped[str | None] = mapped_column(String(36))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    customer_tenant_record_id: Mapped[str | None] = mapped_column(String(36))
    owner_id: Mapped[str | None] = mapped_column(String(36))
    public_access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, default=opaque_token_hash)
    source: Mapped[OrderSource] = mapped_column(enum_column(OrderSource, "order_source"), default=OrderSource.QR, server_default=OrderSource.QR.value)
    service_mode: Mapped[ServiceMode] = mapped_column(enum_column(ServiceMode, "service_mode"), default=ServiceMode.DINE_IN, server_default=ServiceMode.DINE_IN.value)
    status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus, "order_status"), default=OrderStatus.SUBMITTED, server_default=OrderStatus.SUBMITTED.value)
    estimated_wait_minutes: Mapped[int | None] = mapped_column(Integer)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    transfer_notice: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", server_default="NGN")
    vat_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(7, 6), default=Decimal("0"), server_default="0")
    service_charge_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(7, 6), default=Decimal("0"), server_default="0")
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    service_charge_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    lines: Mapped[list[OrderLine]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id"], ["orders.tenant_id", "orders.location_id", "orders.id"], name="fk_order_line_order", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id", "menu_item_id"], ["menu_items.tenant_id", "menu_items.location_id", "menu_items.id"], name="fk_order_line_menu_item"),
        ForeignKeyConstraint(["tenant_id", "location_id", "claimed_by_id"], ["staff_location_assignments.tenant_id", "staff_location_assignments.location_id", "staff_location_assignments.staff_id"], name="fk_order_line_claimed_assignment"),
        UniqueConstraint("tenant_id", "location_id", "id", name="uq_order_line_scope_id"),
        UniqueConstraint("tenant_id", "location_id", "order_id", "id", name="uq_order_line_order_scope_id"),
        CheckConstraint("quantity > 0", name="ck_order_line_quantity"),
        CheckConstraint("unit_price >= 0 AND subtotal_amount >= 0 AND vat_amount >= 0 AND service_charge_amount >= 0 AND total_amount >= 0", name="ck_order_line_amounts_nonnegative"),
        Index("ix_order_line_queue", "tenant_id", "location_id", "queue_destination", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    menu_item_id: Mapped[str] = mapped_column(String(36))
    claimed_by_id: Mapped[str | None] = mapped_column(String(36))
    quantity: Mapped[int] = mapped_column(Integer)
    item_name_snapshot: Mapped[str] = mapped_column(String(160))
    modifiers_snapshot: Mapped[str] = mapped_column(Text, default="", server_default="")
    selected_modifiers: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    special_instruction: Mapped[str | None] = mapped_column(Text)
    queue_destination: Mapped[QueueDestination] = mapped_column(enum_column(QueueDestination, "queue_destination"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    service_charge_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    status: Mapped[LineStatus] = mapped_column(enum_column(LineStatus, "line_status"), default=LineStatus.PENDING, server_default=LineStatus.PENDING.value)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    order: Mapped[Order] = relationship(back_populates="lines", overlaps="location,tenant")


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id"], ["orders.tenant_id", "orders.location_id", "orders.id"], name="fk_payment_attempt_order", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id", "recorded_by_id"], ["staff_location_assignments.tenant_id", "staff_location_assignments.location_id", "staff_location_assignments.staff_id"], name="fk_payment_recorder_assignment"),
        CheckConstraint("amount > 0", name="ck_payment_attempt_amount_positive"),
        UniqueConstraint("tenant_id", "location_id", "order_id", "id", name="uq_payment_attempt_order_scope_id"),
        Index("ix_payment_report_created", "tenant_id", "location_id", "created_at"),
        Index("uq_payment_successful_order", "order_id", unique=True, postgresql_where=text("status = 'SUCCESSFUL'"), sqlite_where=text("status = 'SUCCESSFUL'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    method: Mapped[PaymentMethod] = mapped_column(enum_column(PaymentMethod, "payment_method"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="NGN", server_default="NGN")
    status: Mapped[PaymentStatus] = mapped_column(enum_column(PaymentStatus, "payment_status"), default=PaymentStatus.PENDING, server_default=PaymentStatus.PENDING.value)
    reference: Mapped[str] = mapped_column(String(80), unique=True)
    provider_code: Mapped[str | None] = mapped_column(String(80))
    failure_reason: Mapped[str | None] = mapped_column(String(300))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, default=uid)
    recorded_by_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Payment = PaymentAttempt  # compatibility alias; canonical name is PaymentAttempt


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id"], ["orders.tenant_id", "orders.location_id", "orders.id"], name="fk_refund_order", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id", "manager_id"], ["staff_location_assignments.tenant_id", "staff_location_assignments.location_id", "staff_location_assignments.staff_id"], name="fk_refund_manager_assignment"),
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id", "payment_attempt_id"], ["payment_attempts.tenant_id", "payment_attempts.location_id", "payment_attempts.order_id", "payment_attempts.id"], name="fk_refund_payment_attempt"),
        CheckConstraint("amount > 0", name="ck_refund_amount_positive"),
        Index("uq_refund_successful_order", "order_id", unique=True, postgresql_where=text("status = 'SUCCESSFUL'"), sqlite_where=text("status = 'SUCCESSFUL'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    payment_attempt_id: Mapped[str] = mapped_column(String(36))
    manager_id: Mapped[str] = mapped_column(String(36))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="NGN", server_default="NGN")
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[RefundStatus] = mapped_column(enum_column(RefundStatus, "refund_status"), default=RefundStatus.PENDING, server_default=RefundStatus.PENDING.value)
    reference: Mapped[str] = mapped_column(String(80), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id"], ["orders.tenant_id", "orders.location_id", "orders.id"], name="fk_receipt_order", ondelete="CASCADE"),
        UniqueConstraint("order_id", name="uq_receipt_order"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36))
    receipt_number: Mapped[str] = mapped_column(String(80), unique=True)
    payload_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    email_to: Mapped[str | None] = mapped_column(String(255))
    delivery_status: Mapped[ReceiptDeliveryStatus] = mapped_column(enum_column(ReceiptDeliveryStatus, "receipt_delivery_status"), default=ReceiptDeliveryStatus.NOT_REQUESTED, server_default=ReceiptDeliveryStatus.NOT_REQUESTED.value)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    delivery_error: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], name="fk_reservation_location"),
        ForeignKeyConstraint(["tenant_id", "location_id", "table_id"], ["dining_tables.tenant_id", "dining_tables.location_id", "dining_tables.id"], name="fk_reservation_table"),
        ForeignKeyConstraint(["tenant_id", "location_id", "confirmed_by_id"], ["staff_location_assignments.tenant_id", "staff_location_assignments.location_id", "staff_location_assignments.staff_id"], name="fk_reservation_confirmer_assignment"),
        CheckConstraint("party_size > 0", name="ck_reservation_party_size"),
        Index("ix_reservation_time", "tenant_id", "location_id", "requested_at"),
        UniqueConstraint("public_access_token_hash", name="uq_reservation_public_access_token_hash"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    table_id: Mapped[str | None] = mapped_column(String(36))
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"))
    customer_name: Mapped[str] = mapped_column(String(160))
    customer_phone: Mapped[str] = mapped_column(String(32))
    # Only a SHA-256 digest is persisted.  The corresponding bearer token is
    # returned once when a diner creates a reservation and is never recoverable.
    public_access_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    qr_pass_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    party_size: Mapped[int] = mapped_column(Integer)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[ReservationStatus] = mapped_column(enum_column(ReservationStatus, "reservation_status"), default=ReservationStatus.REQUESTED, server_default=ReservationStatus.REQUESTED.value)
    notes: Mapped[str | None] = mapped_column(Text)
    confirmed_by_id: Mapped[str | None] = mapped_column(String(36))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_by_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ItemRating(Base):
    __tablename__ = "item_ratings"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id"], ["orders.tenant_id", "orders.location_id", "orders.id"], name="fk_item_rating_order", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id", "order_line_id"], ["order_lines.tenant_id", "order_lines.location_id", "order_lines.order_id", "order_lines.id"], name="fk_item_rating_line", ondelete="CASCADE"),
        UniqueConstraint("order_line_id", name="uq_item_rating_line"),
        UniqueConstraint("tenant_id", "location_id", "id", name="uq_item_rating_scope_id"),
        CheckConstraint("score BETWEEN 1 AND 5", name="ck_item_rating_score"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36))
    order_line_id: Mapped[str] = mapped_column(String(36))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OrderRating(Base):
    __tablename__ = "order_ratings"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id"], ["orders.tenant_id", "orders.location_id", "orders.id"], name="fk_order_rating_order", ondelete="CASCADE"),
        UniqueConstraint("order_id", name="uq_order_rating_order"),
        UniqueConstraint("tenant_id", "location_id", "id", name="uq_order_rating_scope_id"),
        CheckConstraint("score BETWEEN 1 AND 5", name="ck_order_rating_score"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Complaint(Base):
    __tablename__ = "complaints"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id", "order_id"], ["orders.tenant_id", "orders.location_id", "orders.id"], name="fk_complaint_order", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id", "order_rating_id"], ["order_ratings.tenant_id", "order_ratings.location_id", "order_ratings.id"], name="fk_complaint_order_rating"),
        ForeignKeyConstraint(["tenant_id", "location_id", "item_rating_id"], ["item_ratings.tenant_id", "item_ratings.location_id", "item_ratings.id"], name="fk_complaint_item_rating"),
        ForeignKeyConstraint(["tenant_id", "location_id", "resolved_by_id"], ["staff_location_assignments.tenant_id", "staff_location_assignments.location_id", "staff_location_assignments.staff_id"], name="fk_complaint_resolver_assignment"),
        Index("ix_complaint_status", "tenant_id", "location_id", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    order_rating_id: Mapped[str | None] = mapped_column(String(36))
    item_rating_id: Mapped[str | None] = mapped_column(String(36))
    subject: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[ComplaintStatus] = mapped_column(enum_column(ComplaintStatus, "complaint_status"), default=ComplaintStatus.OPEN, server_default=ComplaintStatus.OPEN.value)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[str | None] = mapped_column(String(36))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], name="fk_audit_event_location"),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["staff_accounts.tenant_id", "staff_accounts.id"], name="fk_audit_event_actor"),
        Index("ix_audit_subject", "tenant_id", "location_id", "subject_type", "subject_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    location_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(60))
    subject_type: Mapped[str] = mapped_column(String(60))
    subject_id: Mapped[str] = mapped_column(String(36))
    detail: Mapped[str] = mapped_column(Text, default="", server_default="")
    before_data: Mapped[dict | None] = mapped_column(JSON)
    after_data: Mapped[dict | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


@event.listens_for(AuditEvent, "before_update", propagate=True)
@event.listens_for(AuditEvent, "before_delete", propagate=True)
def prevent_audit_mutation(mapper, connection, target) -> None:  # type: ignore[no-untyped-def]
    raise ValueError("Audit events are append-only.")
