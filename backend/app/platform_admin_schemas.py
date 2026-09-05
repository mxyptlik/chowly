"""Contracts for operator-created Chowly tenants and their first location."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.location_schemas import LocationCreateIn, LocationOut, OperatingHourIn


class BootstrapOwnerInviteIn(BaseModel):
    """Optional first tenant-owner invitation delivered by the platform operator."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    email: EmailStr

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name cannot be blank.")
        return normalized


class TenantBootstrapIn(BaseModel):
    """A tenant and exactly one initial, correctly-owned restaurant location."""

    model_config = ConfigDict(extra="forbid")

    tenant_name: str = Field(min_length=2, max_length=160)
    initial_location: LocationCreateIn
    operating_hours: list[OperatingHourIn] = Field(min_length=1, max_length=7)
    owner_invitation: BootstrapOwnerInviteIn | None = None

    @field_validator("tenant_name")
    @classmethod
    def normalize_tenant_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Tenant name cannot be blank.")
        return normalized

    @model_validator(mode="after")
    def require_unique_operating_days(self) -> "TenantBootstrapIn":
        if len({row.weekday for row in self.operating_hours}) != len(self.operating_hours):
            raise ValueError("Provide at most one operating-hours row per weekday.")
        return self


class BootstrapOwnerInviteOut(BaseModel):
    staff_id: str
    email: EmailStr
    expires_at: datetime
    acceptance_token: str


class TenantBootstrapOut(BaseModel):
    tenant_id: str
    tenant_name: str
    initial_location: LocationOut
    owner_invitation: BootstrapOwnerInviteOut | None = None
