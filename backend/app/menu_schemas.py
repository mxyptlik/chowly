from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import MenuItemType, QueueDestination


class MenuCategoryCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=0, le=10000)


class MenuCategoryUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None


class MenuCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    sort_order: int
    is_active: bool


class MenuCategoryListOut(BaseModel):
    items: list[MenuCategoryOut]
    next_cursor: str | None = None
    has_more: bool


class MenuItemCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=3000)
    category_id: str
    item_type: MenuItemType
    queue_destination: QueueDestination
    base_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    available: bool = True
    image_url: str | None = Field(default=None, max_length=1000)

    @field_validator("image_url")
    @classmethod
    def https_image_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not value.startswith("https://"):
            raise ValueError("Image URLs must use HTTPS.")
        return value


class MenuItemUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=3000)
    category_id: str | None = None
    item_type: MenuItemType | None = None
    queue_destination: QueueDestination | None = None
    base_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    available: bool | None = None
    image_url: str | None = Field(default=None, max_length=1000)

    @field_validator("image_url")
    @classmethod
    def https_image_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not value.startswith("https://"):
            raise ValueError("Image URLs must use HTTPS.")
        return value


class SoldOutIn(BaseModel):
    sold_out: bool
    until: datetime | None = None
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def clear_when_available(self) -> "SoldOutIn":
        if not self.sold_out:
            self.until = None
            self.reason = None
        return self


class ModifierGroupCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    minimum_selections: int = Field(default=0, ge=0, le=50)
    maximum_selections: int = Field(default=1, ge=0, le=50)
    sort_order: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def valid_range(self) -> "ModifierGroupCreateIn":
        if self.maximum_selections < self.minimum_selections:
            raise ValueError("maximum_selections must be at least minimum_selections.")
        return self


class ModifierGroupUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    minimum_selections: int | None = Field(default=None, ge=0, le=50)
    maximum_selections: int | None = Field(default=None, ge=0, le=50)
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class ModifierOptionCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price_delta: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    available: bool = True
    sort_order: int = Field(default=0, ge=0, le=10000)


class ModifierOptionUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    price_delta: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    available: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class ModifierOptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    price_delta: Decimal
    final_price_delta: Decimal
    available: bool
    sort_order: int


class ModifierGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    minimum_selections: int
    maximum_selections: int
    sort_order: int
    options: list[ModifierOptionOut]


class MenuItemOut(BaseModel):
    id: str
    name: str
    description: str
    image_url: str | None
    category: MenuCategoryOut
    item_type: MenuItemType
    queue_destination: QueueDestination
    base_price: Decimal
    final_base_price: Decimal
    available: bool
    sold_out_until: datetime | None
    sold_out_reason: str | None
    modifier_groups: list[ModifierGroupOut]


class MenuItemListOut(BaseModel):
    items: list[MenuItemOut]
    next_cursor: str | None = None
    has_more: bool


class MenuSelectionIn(BaseModel):
    menu_item_id: str
    modifier_option_ids: list[str] = Field(default_factory=list, max_length=50)
    quantity: int = Field(default=1, ge=1, le=20)


class PriceBreakdownOut(BaseModel):
    item_subtotal: Decimal
    modifier_subtotal: Decimal
    subtotal: Decimal
    vat: Decimal
    service_charge: Decimal
    total: Decimal
    currency: str


class MenuSelectionOut(BaseModel):
    item: MenuItemOut
    selected_modifier_ids: list[str]
    pricing: PriceBreakdownOut


class PublicMenuOut(BaseModel):
    table_id: str
    table_label: str
    location_id: str
    location_name: str
    timezone: str
    currency: str
    currently_open: bool
    manual_ordering_open: bool
    vat_rate: Decimal
    service_charge_rate: Decimal
    charge_disclosure: str
    operating_hours: list[dict]
    menu: list[MenuItemOut]
