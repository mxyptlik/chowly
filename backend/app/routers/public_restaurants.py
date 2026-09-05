"""Safe, unauthenticated restaurant discovery projections."""
from __future__ import annotations

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.location_service import location_is_currently_open
from app.models import Location, MenuCategory, MenuItem, Tenant, TenantLifecycle
from app.pricing_service import all_in_component_price, menu_item_is_available

router = APIRouter(prefix="/api/v1/public/restaurants", tags=["public restaurants"])


def _location_out(location: Location) -> dict:
    return {"name": location.name, "slug": location.slug, "address": location.address, "cover_image_url": location.cover_image_url, "currency": location.currency, "is_open": location_is_currently_open(location)}


def _tenant_out(tenant: Tenant) -> dict:
    return {"name": tenant.name, "slug": tenant.slug, "description": tenant.description, "cover_image_url": tenant.cover_image_url}


def _visible_tenant_query():
    return select(Tenant).where(Tenant.lifecycle == TenantLifecycle.ACTIVE).options(selectinload(Tenant.locations).selectinload(Location.operating_hours))


@router.get("")
def list_restaurants(db: Session = Depends(get_db)) -> list[dict]:
    tenants = db.scalars(_visible_tenant_query().order_by(Tenant.name, Tenant.id)).unique()
    return [
        {
            **_tenant_out(tenant),
            "locations": [
                _location_out(location)
                for location in sorted(tenant.locations, key=lambda row: (row.name, row.id))
                if location.is_active
            ],
        }
        for tenant in tenants
        if any(location.is_active for location in tenant.locations)
    ]


@router.get("/{tenant_slug}")
def get_restaurant(tenant_slug: str, db: Session = Depends(get_db)) -> dict:
    tenant = db.scalar(_visible_tenant_query().where(Tenant.slug == tenant_slug))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found.")
    return {**_tenant_out(tenant), "locations": [_location_out(location) for location in sorted(tenant.locations, key=lambda row: (row.name, row.id)) if location.is_active]}


@router.get("/{tenant_slug}/locations/{location_slug}")
def get_restaurant_location(tenant_slug: str, location_slug: str, db: Session = Depends(get_db)) -> dict:
    location = db.scalar(
        select(Location).join(Tenant).where(Tenant.slug == tenant_slug, Tenant.lifecycle == TenantLifecycle.ACTIVE, Location.slug == location_slug, Location.is_active.is_(True)).options(selectinload(Location.operating_hours), selectinload(Location.menu_categories).selectinload(MenuCategory.items))
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Restaurant location not found.")
    menu: list[dict] = []
    for category in sorted(location.menu_categories, key=lambda row: (row.sort_order, row.name, row.id)):
        if not category.is_active:
            continue
        items = []
        for item in sorted(category.items, key=lambda row: (row.name, row.id)):
            if not menu_item_is_available(item):
                continue
            items.append({"name": item.name, "description": item.description, "image_url": item.image_url, "item_type": item.item_type.value, "price": all_in_component_price(Decimal(item.base_price), vat_rate=Decimal(location.vat_rate), service_charge_rate=Decimal(location.service_charge_rate)), "currency": location.currency})
        if items:
            menu.append({"name": category.name, "items": items})
    return {"restaurant": _tenant_out(location.tenant), "location": _location_out(location), "menu": menu}
