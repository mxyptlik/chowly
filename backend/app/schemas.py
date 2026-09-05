from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field


class ModifierOut(BaseModel):
    id: str
    name: str
    price_delta: Decimal


class MenuItemOut(BaseModel):
    id: str
    name: str
    description: str
    category: str
    item_type: str
    base_price: Decimal
    available: bool
    modifiers: list[ModifierOut]


class TableContextOut(BaseModel):
    table_id: str
    table_label: str
    location_name: str
    location_open: bool
    vat_rate: Decimal
    service_charge_rate: Decimal
    menu: list[MenuItemOut]


class OrderLineIn(BaseModel):
    menu_item_id: str
    quantity: int = Field(ge=1, le=20)
    modifier_ids: list[str] = []
    special_instruction: str | None = Field(default=None, max_length=400)


class CreateOrderIn(BaseModel):
    customer_name: str = Field(min_length=2, max_length=160)
    customer_phone: str = Field(min_length=7, max_length=32)
    customer_email: EmailStr | None = None
    service_mode: str = "DINE_IN"
    lines: list[OrderLineIn] = Field(min_length=1)


class OrderOut(BaseModel):
    id: str
    status: str
    service_mode: str
    total_amount: Decimal
    table_label: str | None = None
    estimated_wait_minutes: int | None = None


class AcceptOrderIn(BaseModel):
    # A manager may identify a waiter target, but this ID is never the actor.
    # Waiters always act as the authenticated session principal.
    waiter_id: str | None = None
    estimated_wait_minutes: int = Field(ge=1, le=180)


class ClaimLineIn(BaseModel):
    # Transitional clients may still send this field; protected routes ignore it.
    staff_id: str | None = None


class PayOrderIn(BaseModel):
    method: str = Field(pattern="^(CARD|TRANSFER|WALLET|CASH)$")


class DashboardOrderOut(BaseModel):
    id: str
    table_label: str | None
    customer_name: str
    status: str
    service_mode: str
    total_amount: Decimal
    created_at: str
    line_count: int
