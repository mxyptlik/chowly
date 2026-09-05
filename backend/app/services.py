from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Customer, DiningTable, LineStatus, Location, MenuItem, ModifierOption, Order, OrderLine, OrderStatus, Payment, ServiceMode, Staff, TableVisit
from app.schemas import CreateOrderIn


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalized_phone(value: str) -> str:
    return "".join(char for char in value if char.isdigit() or char == "+")


def audit(db: Session, location_id: str, event_type: str, subject_type: str, subject_id: str, actor_id: str | None = None, detail: str = "") -> None:
    location = db.get(Location, location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found.")
    db.add(AuditEvent(tenant_id=location.tenant_id, location_id=location_id, actor_id=actor_id, event_type=event_type, subject_type=subject_type, subject_id=subject_id, detail=detail))


def table_by_code(db: Session, daily_code: str) -> DiningTable:
    table = db.scalar(select(DiningTable).where(DiningTable.daily_code == daily_code))
    if not table:
        raise HTTPException(status_code=404, detail="This table QR code is invalid or has been refreshed.")
    if table.code_issued_on != date.today().isoformat():
        raise HTTPException(status_code=410, detail="This table QR code has expired. Ask a waiter to refresh it.")
    return table


def order_to_out(order: Order, table_label: str | None) -> dict:
    return {
        "id": order.id,
        "status": order.status,
        "service_mode": order.service_mode,
        "total_amount": order.total_amount,
        "table_label": table_label,
        "estimated_wait_minutes": order.estimated_wait_minutes,
    }


def create_order(db: Session, daily_code: str, payload: CreateOrderIn) -> dict:
    table = table_by_code(db, daily_code)
    location = db.get(Location, table.location_id)
    if not location or not location.is_open:
        raise HTTPException(status_code=409, detail="This location is not accepting orders right now.")
    service_mode = payload.service_mode.upper()
    if service_mode not in (ServiceMode.DINE_IN, ServiceMode.TAKEAWAY):
        raise HTTPException(status_code=422, detail="Service mode must be DINE_IN or TAKEAWAY.")

    phone = normalized_phone(payload.customer_phone)
    customer = db.scalar(select(Customer).where(Customer.phone == phone))
    if not customer:
        customer = Customer(name=payload.customer_name.strip(), phone=phone, email=str(payload.customer_email) if payload.customer_email else None)
        db.add(customer)
        db.flush()
    elif payload.customer_email and not customer.email:
        customer.email = str(payload.customer_email)

    order = Order(
        location_id=location.id,
        table_id=table.id if service_mode == ServiceMode.DINE_IN else None,
        customer_id=customer.id,
        service_mode=service_mode,
        status=OrderStatus.SUBMITTED,
    )
    db.add(order)
    db.flush()

    pre_charge_total = Decimal("0")
    for requested in payload.lines:
        item = db.get(MenuItem, requested.menu_item_id)
        if not item or item.location_id != location.id or not item.available:
            raise HTTPException(status_code=409, detail="One or more selected items are unavailable.")
        modifiers: list[ModifierOption] = []
        if requested.modifier_ids:
            modifiers = list(db.scalars(select(ModifierOption).where(ModifierOption.id.in_(requested.modifier_ids), ModifierOption.menu_item_id == item.id)))
            if len(modifiers) != len(requested.modifier_ids):
                raise HTTPException(status_code=422, detail=f"A selected modifier is invalid for {item.name}.")
        unit_price = item.base_price + sum((modifier.price_delta for modifier in modifiers), Decimal("0"))
        modifier_text = ", ".join(modifier.name for modifier in modifiers)
        db.add(OrderLine(
            order_id=order.id,
            menu_item_id=item.id,
            quantity=requested.quantity,
            item_name_snapshot=item.name,
            modifiers_snapshot=modifier_text,
            special_instruction=requested.special_instruction,
            unit_price=money(unit_price),
        ))
        pre_charge_total += unit_price * requested.quantity

    multiplier = Decimal("1") + location.vat_rate + location.service_charge_rate
    order.total_amount = money(pre_charge_total * multiplier)
    audit(db, location.id, "ORDER_SUBMITTED", "ORDER", order.id, detail=f"mode={service_mode}")
    db.commit()
    db.refresh(order)
    return order_to_out(order, table.label if order.table_id else None)


def ensure_staff(db: Session, staff_id: str, location_id: str, roles: set[str]) -> Staff:
    staff = db.get(Staff, staff_id)
    if not staff or staff.location_id != location_id or not staff.is_active or staff.role not in roles:
        raise HTTPException(status_code=403, detail="This staff member cannot perform that action.")
    return staff


def maybe_mark_ready(db: Session, order: Order) -> None:
    if order.lines and all(line.status in (LineStatus.READY, LineStatus.CANCELLED) for line in order.lines):
        order.status = OrderStatus.READY


def reference() -> str:
    return f"CHW-{uuid4().hex[:10].upper()}"
