"""Tenant retention policy and privacy-preserving cleanup semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Customer, CustomerTenantRecord, Tenant


DEFAULT_RETENTION_DAYS = 90
DIRECT_RETENTION_MAX_DAYS = 120


class RetentionError(ValueError):
    pass


class RetentionNotFound(RetentionError):
    pass


class RetentionConflict(RetentionError):
    pass


@dataclass(frozen=True, slots=True)
class CleanupResult:
    tenant_id: str
    cutoff: datetime
    tenant_records_anonymized: int
    global_customers_anonymized: int


def policy_payload(tenant: Tenant) -> dict:
    if tenant.retention_extension_requested_days is not None:
        state = "PENDING_PLATFORM_APPROVAL"
    elif tenant.retention_days > DIRECT_RETENTION_MAX_DAYS:
        state = "APPROVED_EXTENSION"
    else:
        state = "ACTIVE"
    return {
        "tenant_id": tenant.id,
        "effective_days": tenant.retention_days,
        "pending_requested_days": tenant.retention_extension_requested_days,
        "pending_requested_at": tenant.retention_extension_requested_at,
        "extension_approved_at": tenant.retention_extension_approved_at,
        "extension_approved_by": tenant.retention_extension_approved_by,
        "state": state,
    }


def configure_retention(
    db: Session,
    *,
    tenant: Tenant,
    requested_days: int,
    now: datetime | None = None,
) -> Tenant:
    if requested_days < 1:
        raise RetentionError("Retention must be at least one day.")
    current = now or datetime.now(UTC)
    if requested_days <= DIRECT_RETENTION_MAX_DAYS:
        tenant.retention_days = requested_days
        tenant.retention_extension_requested_days = None
        tenant.retention_extension_requested_at = None
        tenant.retention_extension_approved_at = None
        tenant.retention_extension_approved_by = None
    else:
        # The active policy remains unchanged until a platform administrator
        # explicitly approves the requested exception.
        tenant.retention_extension_requested_days = requested_days
        tenant.retention_extension_requested_at = current
    tenant.updated_at = current
    db.commit()
    db.refresh(tenant)
    return tenant


def approve_pending_extension(
    db: Session,
    *,
    tenant: Tenant,
    platform_admin_id: str,
    now: datetime | None = None,
) -> Tenant:
    requested_days = tenant.retention_extension_requested_days
    if requested_days is None or requested_days <= DIRECT_RETENTION_MAX_DAYS:
        raise RetentionConflict("This tenant has no pending retention extension.")
    current = now or datetime.now(UTC)
    tenant.retention_days = requested_days
    tenant.retention_extension_requested_days = None
    tenant.retention_extension_requested_at = None
    tenant.retention_extension_approved_at = current
    tenant.retention_extension_approved_by = platform_admin_id
    tenant.updated_at = current
    db.commit()
    db.refresh(tenant)
    return tenant


def cutoff_for_policy(tenant: Tenant, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=tenant.retention_days)


def _anonymized_phone(record_id: str) -> str:
    # A deterministic non-phone sentinel makes retries harmless and fits the
    # existing 32-character field without exposing the original identity.
    return f"purged-{record_id.replace('-', '')[:24]}"


def cleanup_expired_tenant_records(
    db: Session,
    *,
    tenant_id: str,
    cutoff: datetime,
    now: datetime | None = None,
) -> CleanupResult:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise RetentionNotFound("Tenant not found.")
    current = now or datetime.now(UTC)
    candidates = list(
        db.scalars(
            select(CustomerTenantRecord).where(
                CustomerTenantRecord.tenant_id == tenant_id,
                CustomerTenantRecord.purged_at.is_(None),
                or_(
                    CustomerTenantRecord.last_seen_at <= cutoff,
                    CustomerTenantRecord.purge_after <= current,
                ),
            )
        )
    )
    customer_ids: set[str] = set()
    for record in candidates:
        customer_ids.add(record.customer_id)
        record.name_snapshot = "Anonymized customer"
        record.phone_snapshot = _anonymized_phone(record.id)
        record.email = None
        record.purged_at = current
        record.purge_after = None
    db.flush()

    globally_anonymized = 0
    for customer_id in customer_ids:
        another_tenant_retains_identity = db.scalar(
            select(CustomerTenantRecord.id).where(
                CustomerTenantRecord.customer_id == customer_id,
                CustomerTenantRecord.purged_at.is_(None),
            ).limit(1)
        )
        if another_tenant_retains_identity:
            continue
        customer = db.get(Customer, customer_id)
        if customer is not None:
            customer.name = "Anonymized customer"
            customer.phone = _anonymized_phone(customer.id)
            customer.email = None
            customer.updated_at = current
            globally_anonymized += 1
    db.commit()
    return CleanupResult(
        tenant_id=tenant_id,
        cutoff=cutoff,
        tenant_records_anonymized=len(candidates),
        global_customers_anonymized=globally_anonymized,
    )

