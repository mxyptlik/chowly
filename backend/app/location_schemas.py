from __future__ import annotations

from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class ReservationPolicyIn(BaseModel):
    customer_edits_enabled: bool = True
    customer_edit_cutoff_minutes: int = Field(default=120, ge=0, le=10080)
    customer_cancellations_enabled: bool = True
    customer_cancellation_cutoff_minutes: int = Field(default=30, ge=0, le=10080)


class LocationCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    address: str = Field(min_length=1, max_length=300)
    currency: str = Field(default="NGN", min_length=3, max_length=3)
    vat_rate: Decimal = Field(default=Decimal("0.075"), ge=0, le=1)
    service_charge_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    timezone: str = Field(default="Africa/Lagos", min_length=1, max_length=64)
    is_open: bool = True
    cover_image_url: str | None = Field(default=None, max_length=1000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone.") from exc
        return value

    @field_validator("cover_image_url")
    @classmethod
    def https_image_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not value.startswith("https://"):
            raise ValueError("Image URLs must use HTTPS.")
        return value


class LocationUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    vat_rate: Decimal | None = Field(default=None, ge=0, le=1)
    service_charge_rate: Decimal | None = Field(default=None, ge=0, le=1)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    is_open: bool | None = None
    is_active: bool | None = None
    cover_image_url: str | None = Field(default=None, max_length=1000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone.") from exc
        return value

    @field_validator("cover_image_url")
    @classmethod
    def https_image_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not value.startswith("https://"):
            raise ValueError("Image URLs must use HTTPS.")
        return value


class OperatingHourIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    opens_at: time | None = None
    closes_at: time | None = None
    is_closed: bool = False

    @model_validator(mode="after")
    def validate_times(self) -> "OperatingHourIn":
        if self.is_closed:
            self.opens_at = None
            self.closes_at = None
        elif self.opens_at is None or self.closes_at is None:
            raise ValueError("Open days require opening and closing times.")
        return self


class OperatingHourOut(OperatingHourIn):
    model_config = ConfigDict(from_attributes=True)

    id: str


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    address: str
    currency: str
    vat_rate: Decimal
    service_charge_rate: Decimal
    timezone: str
    is_active: bool
    is_open: bool
    slug: str
    cover_image_url: str | None
    currently_open: bool
    customer_edits_enabled: bool
    customer_edit_cutoff_minutes: int
    customer_cancellations_enabled: bool
    customer_cancellation_cutoff_minutes: int
    operating_hours: list[OperatingHourOut] = []
