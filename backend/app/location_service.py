"""Location operating-state calculations shared by staff and public menu APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.models import Location, OperatingHour


def location_is_currently_open(location: Location, *, now: datetime | None = None) -> bool:
    if not location.is_active or not location.is_open:
        return False
    hours = {row.weekday: row for row in location.operating_hours}
    if not hours:
        return True
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    local = current.astimezone(ZoneInfo(location.timezone))
    today = hours.get(local.weekday())
    current_time = local.timetz().replace(tzinfo=None)
    if today and not today.is_closed and today.opens_at and today.closes_at:
        if today.opens_at <= today.closes_at:
            if today.opens_at <= current_time < today.closes_at:
                return True
        elif current_time >= today.opens_at:
            return True
    previous: OperatingHour | None = hours.get((local.weekday() - 1) % 7)
    return bool(
        previous
        and not previous.is_closed
        and previous.opens_at
        and previous.closes_at
        and previous.opens_at > previous.closes_at
        and current_time < previous.closes_at
    )

