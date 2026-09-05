"""Narrow worker adapter for the P03 retention-cleanup actor."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import SessionLocal
from app.retention_service import cleanup_expired_tenant_records


def _parse_cutoff(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("cutoff_iso must be an ISO-8601 datetime.") from exc


def run_retention_cleanup(
    *,
    tenant_id: str,
    cutoff_iso: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Execute one tenant-scoped cleanup; P03 supplies durable job idempotency."""

    del idempotency_key  # Idempotency is durable in the actor and semantic in SQL.
    with SessionLocal() as db:
        result = cleanup_expired_tenant_records(
            db,
            tenant_id=tenant_id,
            cutoff=_parse_cutoff(cutoff_iso),
        )
    return {
        "tenant_id": result.tenant_id,
        "cutoff": result.cutoff.isoformat(),
        "tenant_records_anonymized": result.tenant_records_anonymized,
        "global_customers_anonymized": result.global_customers_anonymized,
    }

