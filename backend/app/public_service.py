"""Public identity helpers; slugs are stable identifiers, never authorization."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return text[:160] or "restaurant"


def unique_tenant_slug(db: Session, name: str) -> str:
    from app.models import Tenant

    base = slugify(name)
    candidate, suffix = base, 2
    while db.scalar(select(Tenant.id).where(Tenant.slug == candidate)):
        candidate = f"{base[:150]}-{suffix}"
        suffix += 1
    return candidate


def unique_location_slug(db: Session, *, tenant_id: str, name: str) -> str:
    from app.models import Location

    base = slugify(name)
    candidate, suffix = base, 2
    while db.scalar(select(Location.id).where(Location.tenant_id == tenant_id, Location.slug == candidate)):
        candidate = f"{base[:150]}-{suffix}"
        suffix += 1
    return candidate
