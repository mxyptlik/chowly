"""Transport contracts for tenant customer-data retention configuration."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RetentionConfigureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1)


class RetentionPolicyOut(BaseModel):
    tenant_id: str
    effective_days: int
    pending_requested_days: int | None
    pending_requested_at: datetime | None
    extension_approved_at: datetime | None
    extension_approved_by: str | None
    state: str


class RetentionCleanupOut(BaseModel):
    tenant_id: str
    cutoff: datetime
    tenant_records_anonymized: int
    global_customers_anonymized: int

