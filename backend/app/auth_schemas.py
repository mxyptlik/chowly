"""HTTP contracts for invitation-created staff accounts and staff sessions."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import StaffRole
from typing import Literal

class StaffLocationOut(BaseModel):
    id: str
    tenant_id: str
    name: str


class StaffSessionOut(BaseModel):
    staff_id: str
    name: str
    email: str
    roles: list[StaffRole]
    locations: list[StaffLocationOut]
    active_tenant_id: str | None = None
    active_location_id: str | None = None

class DemoSessionIn(BaseModel):
    """A tightly-scoped assessor persona; platform admin is intentionally excluded."""

    persona: Literal[
        "WAITER",
        "CHEF",
        "BARTENDER",
        "MANAGER",
        "TENANT_OWNER",
    ]
class StaffLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=72)


class StaffInviteIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    roles: list[StaffRole] = Field(min_length=1)
    location_ids: list[str] = Field(min_length=1)

    @field_validator("roles", "location_ids")
    @classmethod
    def values_must_be_unique(cls, values: list) -> list:
        if len(values) != len(set(values)):
            raise ValueError("Values must be unique.")
        return values


class StaffInviteOut(BaseModel):
    staff_id: str
    email: EmailStr
    expires_at: datetime
    acceptance_token: str


class StaffAssignmentOut(BaseModel):
    """Tenant-owner safe projection of a staff account and its active grants."""

    id: str
    name: str
    email: EmailStr | None = None
    invitation_status: str
    is_active: bool
    roles: list[StaffRole]
    locations: list[StaffLocationOut]


class StaffAssignmentUpdateIn(BaseModel):
    """The complete replacement set for a tenant staff member's active grants."""

    roles: list[StaffRole] = Field(min_length=1)
    location_ids: list[str] = Field(min_length=1)

    @field_validator("roles", "location_ids")
    @classmethod
    def values_must_be_unique(cls, values: list) -> list:
        if len(values) != len(set(values)):
            raise ValueError("Values must be unique.")
        return values


class StaffInviteAcceptIn(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=10, max_length=72)


class ActiveLocationIn(BaseModel):
    location_id: str


class RealtimeGrantIn(BaseModel):
    location_id: str
    role: StaffRole


class RealtimeGrantOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: datetime
    tenant_id: str
    location_id: str
    role: StaffRole
