"""Transport contracts for public ordering and location-scoped order operations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models import LineStatus, OrderSource, OrderStatus, QueueDestination, ServiceMode, StaffRole
from app.menu_schemas import MenuItemOut


class OrderLineSelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    menu_item_id: str
    quantity: int = Field(ge=1, le=20)
    modifier_option_ids: list[str] = Field(default_factory=list, max_length=20)
    special_instruction: str | None = Field(default=None, max_length=400)


class CustomerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=7, max_length=32)
    email: EmailStr | None = None

    @field_validator("name", "phone")
    @classmethod
    def strip_required(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("This field is required.")
        return clean


class PublicOrderCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer: CustomerIn
    service_mode: ServiceMode = ServiceMode.DINE_IN
    lines: list[OrderLineSelectionIn] = Field(min_length=1, max_length=50)


class ManualOrderCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: str
    customer: CustomerIn
    service_mode: ServiceMode
    table_id: str | None = None
    waiter_id: str | None = None
    estimated_wait_minutes: int = Field(default=15, ge=1, le=180)
    lines: list[OrderLineSelectionIn] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def table_matches_mode(self) -> "ManualOrderCreateIn":
        if self.service_mode == ServiceMode.DINE_IN and not self.table_id:
            raise ValueError("A dine-in manual order requires a table.")
        if self.service_mode == ServiceMode.TAKEAWAY and self.table_id:
            raise ValueError("A takeaway manual order cannot be assigned to a table.")
        return self


class ManualOrderTableOut(BaseModel):
    id: str
    label: str
    capacity: int
    is_active: bool


class ManualOrderCatalogOut(BaseModel):
    """Human-readable, location-scoped choices for a staff-created order."""

    location_id: str
    currency: str
    tables: list[ManualOrderTableOut]
    menu: list[MenuItemOut]


class VersionedMutationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: str


class PublicServiceModeIn(VersionedMutationIn):
    service_mode: ServiceMode


class PublicCancelIn(VersionedMutationIn):
    reason: str = Field(default="Cancelled by diner", min_length=3, max_length=300)


class AcceptOrderIn(VersionedMutationIn):
    waiter_id: str | None = None
    chef_id: str | None = None
    bartender_id: str | None = None
    estimated_wait_minutes: int = Field(ge=1, le=180)


class DelayOrderIn(VersionedMutationIn):
    reason: str = Field(min_length=3, max_length=500)
    estimated_wait_minutes: int | None = Field(default=None, ge=1, le=180)


class PreparerOut(BaseModel):
    id: str
    name: str
    roles: list[StaffRole]


class ReasonedMutationIn(VersionedMutationIn):
    reason: str = Field(min_length=3, max_length=500)


class ReassignOrderIn(ReasonedMutationIn):
    waiter_id: str


class TransferOrderIn(ReasonedMutationIn):
    table_id: str


class AmendOrderLineIn(ReasonedMutationIn):
    quantity: int | None = Field(default=None, ge=1, le=20)
    modifier_option_ids: list[str] | None = Field(default=None, max_length=20)
    special_instruction: str | None = Field(default=None, max_length=400)
    cancel_line: bool = False

    @model_validator(mode="after")
    def change_requested(self) -> "AmendOrderLineIn":
        if (
            self.quantity is None
            and self.modifier_option_ids is None
            and "special_instruction" not in self.model_fields_set
            and not self.cancel_line
        ):
            raise ValueError("Specify a line change or cancellation.")
        if self.cancel_line and any(
            (
                self.quantity is not None,
                self.modifier_option_ids is not None,
                "special_instruction" in self.model_fields_set,
            )
        ):
            raise ValueError("A cancelled line cannot also be amended.")
        return self


class SetWaitTimeIn(VersionedMutationIn):
    minutes: int = Field(ge=1, le=180)
    source: Literal["SUGGESTION", "MANUAL"] = "SUGGESTION"

    @model_validator(mode="after")
    def valid_suggestion(self) -> "SetWaitTimeIn":
        if self.source == "SUGGESTION" and self.minutes not in {5, 10, 15, 30, 45}:
            raise ValueError("Suggested wait time must be 5, 10, 15, 30, or 45 minutes.")
        return self


class PrepMutationIn(VersionedMutationIn):
    pass


class ModifierSnapshotOut(BaseModel):
    id: str
    name: str
    price_delta: Decimal


class OrderLineOut(BaseModel):
    id: str
    menu_item_id: str
    item_name: str
    quantity: int
    base_unit_price: Decimal
    modifiers: list[ModifierSnapshotOut]
    special_instruction: str | None
    queue_destination: QueueDestination
    status: LineStatus
    subtotal_amount: Decimal
    vat_amount: Decimal
    service_charge_amount: Decimal
    total_amount: Decimal
    claimed_at: datetime | None
    ready_at: datetime | None
    cancelled_at: datetime | None


class PublicOrderLineOut(BaseModel):
    id: str
    menu_item_id: str
    item_name: str
    quantity: int
    base_unit_price: Decimal
    modifiers: list[ModifierSnapshotOut]
    special_instruction: str | None
    subtotal_amount: Decimal
    vat_amount: Decimal
    service_charge_amount: Decimal
    total_amount: Decimal


class PublicOrderOut(BaseModel):
    id: str
    status: OrderStatus
    diner_status: OrderStatus
    service_mode: ServiceMode
    table_id: str | None
    table_label: str | None
    transfer_notice: str | None
    estimated_wait_minutes: int | None
    delay_reason: str | None
    delayed_at: datetime | None
    recommended_wait_minutes: int
    wait_time_suggestions: list[int]
    currency: str
    subtotal_amount: Decimal
    vat_amount: Decimal
    service_charge_amount: Decimal
    total_amount: Decimal
    lines: list[PublicOrderLineOut]
    version: str
    created_at: datetime
    accepted_at: datetime | None
    ready_at: datetime | None
    served_at: datetime | None
    cancelled_at: datetime | None
    # This is the diner-facing explanation supplied when the order was
    # cancelled.  It deliberately carries no staff identity or audit data.
    cancellation_reason: str | None


class PublicOrderCreatedOut(PublicOrderOut):
    access_token: str
    realtime_token: str


class StaffOrderOut(PublicOrderOut):
    tenant_id: str
    location_id: str
    source: OrderSource
    owner_id: str | None
    owner_name: str | None
    customer: dict[str, str | None] | None
    lines: list[OrderLineOut]


class StaffOrderCreatedOut(StaffOrderOut):
    access_token: str
    realtime_token: str


class PrepLineOut(BaseModel):
    line_id: str
    order_id: str
    table_label: str
    item_name: str
    quantity: int
    modifiers: list[ModifierSnapshotOut]
    special_instruction: str | None
    queue_destination: QueueDestination
    status: LineStatus
    claimed_by_id: str | None
    claimed_at: datetime | None
    order_version: str


class AuditEventOut(BaseModel):
    id: str
    event_type: str
    subject_type: str
    subject_id: str
    actor_id: str | None
    reason: str
    before_data: dict | None
    after_data: dict | None
    request_id: str | None
    created_at: datetime
