"""Canonical Decimal pricing and menu-selection validation for Chowly V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import MenuItem, ModifierGroup, ModifierOption


MONEY = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def menu_item_is_available(item: MenuItem, *, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    temporarily_sold_out = bool(
        item.sold_out_until and _as_utc(item.sold_out_until) > _as_utc(current)
    )
    return bool(item.available and not temporarily_sold_out)


@dataclass(frozen=True, slots=True)
class PriceBreakdown:
    item_subtotal: Decimal
    modifier_subtotal: Decimal
    subtotal: Decimal
    vat: Decimal
    service_charge: Decimal
    total: Decimal


def price_breakdown(
    *,
    base_price: Decimal,
    modifier_prices: list[Decimal] | tuple[Decimal, ...],
    quantity: int,
    vat_rate: Decimal,
    service_charge_rate: Decimal,
) -> PriceBreakdown:
    if quantity < 1:
        raise ValueError("Quantity must be positive.")
    if any(value < 0 for value in (base_price, vat_rate, service_charge_rate, *modifier_prices)):
        raise ValueError("Prices and charge rates cannot be negative.")
    item_subtotal = money(base_price * quantity)
    modifier_subtotal = money(sum(modifier_prices, ZERO) * quantity)
    subtotal = money(item_subtotal + modifier_subtotal)
    vat = money(subtotal * vat_rate)
    service_charge = money(subtotal * service_charge_rate)
    return PriceBreakdown(
        item_subtotal=item_subtotal,
        modifier_subtotal=modifier_subtotal,
        subtotal=subtotal,
        vat=vat,
        service_charge=service_charge,
        total=money(subtotal + vat + service_charge),
    )


def all_in_component_price(
    price: Decimal,
    *,
    vat_rate: Decimal,
    service_charge_rate: Decimal,
) -> Decimal:
    return money(price * (Decimal("1") + vat_rate + service_charge_rate))


class MenuSelectionError(ValueError):
    def __init__(self, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.unavailable = unavailable


@dataclass(frozen=True, slots=True)
class ValidatedSelection:
    item: MenuItem
    options: tuple[ModifierOption, ...]


def validate_menu_selection(
    db: Session,
    *,
    tenant_id: str,
    location_id: str,
    menu_item_id: str,
    modifier_option_ids: list[str],
    now: datetime | None = None,
) -> ValidatedSelection:
    item = db.scalar(
        select(MenuItem)
        .options(
            selectinload(MenuItem.modifier_groups).selectinload(ModifierGroup.options),
            selectinload(MenuItem.modifiers),
        )
        .where(
            MenuItem.id == menu_item_id,
            MenuItem.tenant_id == tenant_id,
            MenuItem.location_id == location_id,
        )
    )
    if item is None:
        raise MenuSelectionError("Menu item not found.")
    if item.menu_category is not None and not item.menu_category.is_active:
        raise MenuSelectionError("This menu category is currently unavailable.", unavailable=True)
    if not menu_item_is_available(item, now=now):
        raise MenuSelectionError("This menu item is currently unavailable.", unavailable=True)
    if len(modifier_option_ids) != len(set(modifier_option_ids)):
        raise MenuSelectionError("A modifier option cannot be selected more than once.")

    option_by_id = {option.id: option for option in item.modifiers}
    unknown = set(modifier_option_ids).difference(option_by_id)
    if unknown:
        raise MenuSelectionError("One or more modifier options do not belong to this menu item.")
    selected = tuple(option_by_id[option_id] for option_id in modifier_option_ids)
    if any(not option.available for option in selected):
        raise MenuSelectionError("One or more modifier options are unavailable.", unavailable=True)

    selected_by_group: dict[str, int] = {}
    for option in selected:
        if option.group_id:
            selected_by_group[option.group_id] = selected_by_group.get(option.group_id, 0) + 1
    for group in item.modifier_groups:
        count = selected_by_group.get(group.id, 0)
        if count < group.minimum_selections or count > group.maximum_selections:
            raise MenuSelectionError(
                f"{group.name} requires between {group.minimum_selections} and "
                f"{group.maximum_selections} selections."
            )
    return ValidatedSelection(item=item, options=selected)
