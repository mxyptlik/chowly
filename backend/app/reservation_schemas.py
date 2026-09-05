"""Request and response contracts for the V1 reservation workflow."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import ReservationStatus


class ReservationCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(min_length=2, max_length=160)
    customer_phone: str = Field(min_length=7, max_length=32)
    # Public callers use tenant/location slugs; location_id remains for the
    # existing table/internal integrations during the transition.
    location_id: str | None = Field(default=None, min_length=1, max_length=36)
    tenant_slug: str | None = Field(default=None, min_length=1, max_length=180)
    location_slug: str | None = Field(default=None, min_length=1, max_length=180)
    party_size: int = Field(ge=1, le=100)
    requested_at: datetime
    table_id: str | None = Field(default=None, max_length=36)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("customer_name", "customer_phone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("This field cannot be blank.")
        return stripped

    @field_validator("requested_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Reservation time must include a timezone offset.")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("tenant_slug", "location_slug")
    @classmethod
    def normalize_slug(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None


class ReservationPublicOut(BaseModel):
    id: str
    location_id: str
    table_id: str | None
    party_size: int
    requested_at: datetime
    status: ReservationStatus
    created_at: datetime


class ReservationPublicCreatedOut(ReservationPublicOut):
    """Creation acknowledgement.  ``access_token`` is intentionally one-time."""

    access_token: str = Field(min_length=32, max_length=255)


class ReservationPublicUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    party_size: int = Field(ge=1, le=100)
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Reservation time must include a timezone offset.")
        return value


class ReservationQrPassOut(BaseModel):
    qr_pass_token: str = Field(min_length=32, max_length=255)


class ReservationContactOut(BaseModel):
    name: str
    phone: str


class ReservationStaffOut(ReservationPublicOut):
    contact: ReservationContactOut
    note: str | None
    confirmed_by_id: str | None
    confirmed_at: datetime | None
    updated_at: datetime


class ReservationConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str | None = Field(default=None, max_length=36)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ReservationReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=2, max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("A reason is required.")
        return stripped


class ReservationSeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str | None = Field(default=None, max_length=36)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
