"""Idempotent Dramatiq jobs with Redis-backed execution state."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import dramatiq

from app.core.config import get_settings
from app.worker import broker, job_state_redis


JobCallable = Callable[..., Any]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _receipt_delivery_adapter(
    *, order_id: str, email: str, idempotency_key: str
) -> dict[str, Any]:
    """Late-bind P06's SQL-backed delivery contract for worker isolation."""

    from app.receipt_service import deliver_receipt_email

    return deliver_receipt_email(
        order_id=order_id,
        email=email,
        idempotency_key=idempotency_key,
    )


def _retention_cleanup_adapter(
    *, tenant_id: str, cutoff_iso: str, idempotency_key: str
) -> dict[str, Any]:
    """Late-bind the P08 retention service without importing its models in P03."""

    try:
        from app.retention import run_retention_cleanup
    except ImportError as exc:  # pragma: no cover - exercised once P08 integrates.
        raise RuntimeError("Retention cleanup service is not installed yet.") from exc
    return run_retention_cleanup(
        tenant_id=tenant_id,
        cutoff_iso=cutoff_iso,
        idempotency_key=idempotency_key,
    )


def _state_key(job_kind: str, idempotency_key: str) -> str:
    return f"chowly:jobs:{job_kind}:{idempotency_key}"


def _lock_key(job_kind: str, idempotency_key: str) -> str:
    return f"{_state_key(job_kind, idempotency_key)}:lock"


def _decode(value: Any) -> str | None:
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _execute_idempotent(
    job_kind: str,
    idempotency_key: str,
    callback: JobCallable,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run once logically and retain durable attempts/result state in Redis.

    The idempotency key is also passed to the external adapter. This is
    necessary because a worker can die after the provider succeeds but before
    Redis records completion.
    """

    settings = get_settings()
    redis = job_state_redis()
    state_key = _state_key(job_kind, idempotency_key)
    if _decode(redis.hget(state_key, "status")) == "completed":
        return {"status": "duplicate", "idempotency_key": idempotency_key}

    acquired = redis.set(
        _lock_key(job_kind, idempotency_key),
        _utc_now(),
        nx=True,
        ex=300,
    )
    if not acquired:
        return {"status": "in_progress", "idempotency_key": idempotency_key}

    try:
        attempts = int(redis.hincrby(state_key, "attempts", 1))
        redis.hset(
            state_key,
            mapping={"status": "running", "updated_at": _utc_now()},
        )
        result = callback(idempotency_key=idempotency_key, **kwargs) or {}
        redis.hset(
            state_key,
            mapping={
                "status": "completed",
                "attempts": str(attempts),
                "completed_at": _utc_now(),
                "result": json.dumps(result, sort_keys=True, default=str),
            },
        )
        # Completed markers intentionally have no TTL. Redis AOF persistence plus
        # provider-side idempotency prevents a receipt or cleanup being replayed
        # after an arbitrary cache window.
        return {"status": "completed", "idempotency_key": idempotency_key, "result": result}
    except Exception as exc:
        redis.hset(
            state_key,
            mapping={
                "status": "failed",
                "updated_at": _utc_now(),
                "last_error": f"{type(exc).__name__}: {exc}"[:1000],
            },
        )
        redis.expire(state_key, settings.job_state_ttl_seconds)
        raise
    finally:
        redis.delete(_lock_key(job_kind, idempotency_key))


@dramatiq.actor(
    broker=broker,
    max_retries=5,
    min_backoff=1_000,
    max_backoff=60_000,
    time_limit=60_000,
)
def send_receipt_email(order_id: str, email: str, receipt_version: str = "v1") -> dict[str, Any]:
    """Deliver a receipt once; repeated messages return without redelivery."""

    idempotency_key = f"{order_id}:{receipt_version}:{email.strip().lower()}"
    return _execute_idempotent(
        "receipt",
        idempotency_key,
        _receipt_delivery_adapter,
        order_id=order_id,
        email=email.strip().lower(),
    )


@dramatiq.actor(
    broker=broker,
    max_retries=7,
    min_backoff=5_000,
    max_backoff=300_000,
    time_limit=900_000,
)
def cleanup_tenant_retention(
    tenant_id: str,
    cutoff_iso: str,
    policy_version: str = "v1",
) -> dict[str, Any]:
    """Run one tenant/cutoff cleanup once; P08 owns the cleanup semantics."""

    idempotency_key = f"{tenant_id}:{cutoff_iso}:{policy_version}"
    return _execute_idempotent(
        "retention",
        idempotency_key,
        _retention_cleanup_adapter,
        tenant_id=tenant_id,
        cutoff_iso=cutoff_iso,
    )
