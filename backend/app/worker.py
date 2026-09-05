"""Shared Dramatiq/Redis worker configuration."""

from __future__ import annotations

from functools import lru_cache

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from redis import Redis

from app.core.config import get_settings


settings = get_settings()
broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(broker)


@lru_cache
def job_state_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)
