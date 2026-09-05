"""Location-scoped menu administration and public QR menu projection."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth import CurrentStaff
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import assert_location_access, require_roles, scoped_resource_or_404
from app.events import (
    EventBus,
    EventDraft,
    EventResource,
    EventScope,
    EventType,
    ResourceKind,
    commit_and_publish,
    staff_channel,
    stage_domain_event,
)
from app.location_service import location_is_currently_open
from app.menu_schemas import (
    MenuCategoryCreateIn,
    MenuCategoryOut,
    MenuCategoryListOut,
    MenuCategoryUpdateIn,
    MenuItemCreateIn,
    MenuItemOut,
    MenuItemListOut,
    MenuItemUpdateIn,
    MenuSelectionIn,
    MenuSelectionOut,
    ModifierGroupCreateIn,
    ModifierGroupOut,
    ModifierGroupUpdateIn,
    ModifierOptionCreateIn,
    ModifierOptionOut,
    ModifierOptionUpdateIn,
    PublicMenuOut,
    SoldOutIn,
)
from app.models import (
    AuditEvent,
    Location,
    MenuCategory,
    MenuItem,
    MenuItemType,
    DiningTable,
    ModifierGroup,
    ModifierOption,
    QueueDestination,
    StaffRole,
)
from app.pagination import decode_cursor, page_payload
from app.order_schemas import ManualOrderCatalogOut
from app.pricing_service import (
    MenuSelectionError,
    all_in_component_price,
    menu_item_is_available,
    price_breakdown,
    validate_menu_selection,
)
from app.qr_service import InvalidTableQr, calculate_table_activity, resolve_table_qr
from app.realtime import RedisEventBus


PUBLIC_PREFIX = "/api/v1/public/tables"
STAFF_PREFIX = "/api/v1/staff/locations"
EVENT_ROLES = (
    StaffRole.TENANT_OWNER,
    StaffRole.MANAGER,
    StaffRole.WAITER,
    StaffRole.CHEF,
    StaffRole.BARTENDER,
)

FULL_MENU_ADMIN_ROLES = frozenset({StaffRole.TENANT_OWNER, StaffRole.MANAGER})
PREP_MENU_ROLES = frozenset({StaffRole.CHEF, StaffRole.BARTENDER})
# Preparation staff can maintain operational descriptions/images and availability
# for their station.  Pricing, category placement, routing, and modifiers remain
# a manager/owner decision so a station cannot silently alter commercial rules.
PREP_ITEM_UPDATE_FIELDS = frozenset({"name", "description", "image_url", "available"})


def _is_full_menu_admin(current: CurrentStaff) -> bool:
    return current.has_any_role(FULL_MENU_ADMIN_ROLES)


def _prep_destinations(current: CurrentStaff) -> frozenset[QueueDestination]:
    destinations: set[QueueDestination] = set()
    if StaffRole.CHEF in current.roles:
        destinations.add(QueueDestination.KITCHEN)
    if StaffRole.BARTENDER in current.roles:
        destinations.add(QueueDestination.BAR)
    return frozenset(destinations)


def _assert_prep_item_access(current: CurrentStaff, item: MenuItem) -> None:
    """Allow prep staff only within their own station; owners/managers are unrestricted."""
    if _is_full_menu_admin(current):
        return
    if item.queue_destination not in _prep_destinations(current):
        raise HTTPException(status_code=403, detail="This preparation station cannot manage that menu item.")


def _assert_prep_create_access(current: CurrentStaff, payload: MenuItemCreateIn) -> None:
    if _is_full_menu_admin(current):
        return
    expected_type = (
        MenuItemType.FOOD if payload.queue_destination == QueueDestination.KITCHEN else MenuItemType.DRINK
    )
    if (
        payload.queue_destination not in _prep_destinations(current)
        or payload.item_type != expected_type
    ):
        raise HTTPException(status_code=403, detail="This preparation station cannot create that menu item.")


def _assert_prep_update_access(current: CurrentStaff, item: MenuItem, changes: dict) -> None:
    _assert_prep_item_access(current, item)
    if not _is_full_menu_admin(current) and not set(changes).issubset(PREP_ITEM_UPDATE_FIELDS):
        raise HTTPException(
            status_code=403,
            detail="Preparation staff cannot change menu pricing, category, type, or routing.",
        )


def _item_query():
    return select(MenuItem).options(
        joinedload(MenuItem.menu_category),
        selectinload(MenuItem.modifier_groups).selectinload(ModifierGroup.options),
    )


def _item_out(item: MenuItem, location: Location, *, now: datetime | None = None) -> dict:
    vat = Decimal(location.vat_rate)
    service = Decimal(location.service_charge_rate)
    groups: list[dict] = []
    for group in sorted(item.modifier_groups, key=lambda row: (row.sort_order, row.name, row.id)):
        groups.append(
            {
                "id": group.id,
                "name": group.name,
                "minimum_selections": group.minimum_selections,
                "maximum_selections": group.maximum_selections,
                "sort_order": group.sort_order,
                "options": [
                    {
                        "id": option.id,
                        "name": option.name,
                        "price_delta": option.price_delta,
                        "final_price_delta": all_in_component_price(
                            Decimal(option.price_delta),
                            vat_rate=vat,
                            service_charge_rate=service,
                        ),
                        "available": option.available,
                        "sort_order": option.sort_order,
                    }
                    for option in sorted(group.options, key=lambda row: (row.sort_order, row.name, row.id))
                ],
            }
        )
    category = item.menu_category or {
        "id": item.category_id or f"legacy:{item.category}",
        "name": item.category,
        "sort_order": 0,
        "is_active": True,
    }
    category_active = category.is_active if isinstance(category, MenuCategory) else True
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "image_url": item.image_url,
        "category": category,
        "item_type": item.item_type,
        "queue_destination": item.queue_destination,
        "base_price": item.base_price,
        "final_base_price": all_in_component_price(
            Decimal(item.base_price), vat_rate=vat, service_charge_rate=service
        ),
        "available": bool(category_active and menu_item_is_available(item, now=now)),
        "sold_out_until": item.sold_out_until,
        "sold_out_reason": item.sold_out_reason,
        "modifier_groups": groups,
    }


def _audit(
    db: Session,
    *,
    current: CurrentStaff,
    location: Location,
    event_type: str,
    subject_type: str,
    subject_id: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=location.tenant_id,
            location_id=location.id,
            actor_id=current.staff_id,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            before_data=before,
            after_data=after,
        )
    )


def _stage_availability_event(
    db: Session,
    *,
    location: Location,
    resource_id: str,
    payload: dict,
) -> None:
    draft = EventDraft(
        type=EventType.MENU_AVAILABILITY_CHANGED,
        scope=EventScope(tenant_id=location.tenant_id, location_id=location.id),
        resource=EventResource(kind=ResourceKind.MENU_AVAILABILITY, id=resource_id),
        payload=payload,
    )
    for role in EVENT_ROLES:
        stage_domain_event(db, staff_channel(location.tenant_id, location.id, role.value), draft)


def _location(db: Session, current: CurrentStaff, location_id: str) -> Location:
    assert_location_access(current, location_id)
    row = db.scalar(
        select(Location)
        .options(selectinload(Location.operating_hours))
        .where(Location.id == location_id, Location.tenant_id == current.tenant_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return row


def create_menu_router(event_bus: EventBus | None = None) -> APIRouter:
    active_bus = event_bus or RedisEventBus(get_settings().redis_url)
    menu_router = APIRouter(tags=["menu"])

    @menu_router.get(
        f"{STAFF_PREFIX}/{{location_id}}/manual-order-catalog",
        response_model=ManualOrderCatalogOut,
    )
    def manual_order_catalog(
        location_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.WAITER, StaffRole.MANAGER)),
    ) -> dict:
        """Return staff-facing choices by name, while keeping opaque IDs internal."""
        location = _location(db, current, location_id)
        tables = list(
            db.scalars(
                select(DiningTable)
                .where(
                    DiningTable.tenant_id == current.tenant_id,
                    DiningTable.location_id == location_id,
                    DiningTable.is_enabled.is_(True),
                )
                .order_by(DiningTable.label, DiningTable.id)
            )
        )
        items = db.scalars(
            _item_query()
            .where(MenuItem.tenant_id == current.tenant_id, MenuItem.location_id == location_id)
            .order_by(MenuItem.category, MenuItem.name, MenuItem.id)
        ).unique()
        return {
            "location_id": location.id,
            "currency": location.currency,
            "tables": [
                {
                    "id": table.id,
                    "label": table.label,
                    "capacity": table.capacity,
                    "is_active": calculate_table_activity(db, table),
                }
                for table in tables
            ],
            "menu": [
                _item_out(item, location)
                for item in items
                if item.menu_category is None or item.menu_category.is_active
            ],
        }

    @menu_router.get(f"{STAFF_PREFIX}/{{location_id}}/menu/categories", response_model=list[MenuCategoryOut])
    def list_categories(
        location_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.CHEF, StaffRole.BARTENDER)
        ),
    ) -> list[MenuCategory]:
        _location(db, current, location_id)
        return list(
            db.scalars(
                select(MenuCategory)
                .where(
                    MenuCategory.tenant_id == current.tenant_id,
                    MenuCategory.location_id == location_id,
                )
                .order_by(MenuCategory.sort_order, MenuCategory.name, MenuCategory.id)
            )
        )

    @menu_router.get(f"{STAFF_PREFIX}/{{location_id}}/menu/categories/list", response_model=MenuCategoryListOut)
    def list_categories_page(
        location_id: str,
        limit: int = 25,
        cursor: str | None = None,
        active: bool | None = None,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.CHEF, StaffRole.BARTENDER)),
    ) -> dict:
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100.")
        _location(db, current, location_id)
        query = select(MenuCategory).where(MenuCategory.tenant_id == current.tenant_id, MenuCategory.location_id == location_id)
        if active is not None:
            query = query.where(MenuCategory.is_active.is_(active))
        values = decode_cursor(cursor)
        if values is not None:
            if len(values) != 3:
                raise HTTPException(status_code=422, detail="Invalid pagination cursor.")
            sort_order, name, row_id = values
            query = query.where(or_(MenuCategory.sort_order > sort_order, (MenuCategory.sort_order == sort_order) & (MenuCategory.name > name), (MenuCategory.sort_order == sort_order) & (MenuCategory.name == name) & (MenuCategory.id > row_id)))
        rows = list(db.scalars(query.order_by(MenuCategory.sort_order, MenuCategory.name, MenuCategory.id).limit(limit + 1)))
        return page_payload(rows, limit=limit, cursor_for=lambda row: (row.sort_order, row.name, row.id))

    @menu_router.post(
        f"{STAFF_PREFIX}/{{location_id}}/menu/categories",
        response_model=MenuCategoryOut,
        status_code=status.HTTP_201_CREATED,
    )
    def create_category(
        location_id: str,
        payload: MenuCategoryCreateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> MenuCategory:
        location = _location(db, current, location_id)
        category = MenuCategory(
            tenant_id=location.tenant_id,
            location_id=location.id,
            **payload.model_dump(),
        )
        db.add(category)
        try:
            db.flush()
            _audit(
                db,
                current=current,
                location=location,
                event_type="MENU_CATEGORY_CREATED",
                subject_type="MENU_CATEGORY",
                subject_id=category.id,
                after=payload.model_dump(mode="json"),
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="This category name already exists.") from None
        return category

    @menu_router.patch(
        f"{STAFF_PREFIX}/{{location_id}}/menu/categories/{{category_id}}",
        response_model=MenuCategoryOut,
    )
    def update_category(
        location_id: str,
        category_id: str,
        payload: MenuCategoryUpdateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> MenuCategory:
        location = _location(db, current, location_id)
        category = scoped_resource_or_404(db, MenuCategory, category_id, current, location_id=location_id)
        changes = payload.model_dump(exclude_unset=True)
        before = {key: getattr(category, key) for key in changes}
        for key, value in changes.items():
            setattr(category, key, value)
        if "name" in changes:
            for item in category.items:
                item.category = category.name
        _audit(
            db,
            current=current,
            location=location,
            event_type="MENU_CATEGORY_UPDATED",
            subject_type="MENU_CATEGORY",
            subject_id=category.id,
            before=before,
            after=payload.model_dump(mode="json", exclude_unset=True),
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="The category update conflicts with existing data.") from None
        return category

    @menu_router.delete(
        f"{STAFF_PREFIX}/{{location_id}}/menu/categories/{{category_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_model=None,
    )
    def delete_category(
        location_id: str,
        category_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> None:
        location = _location(db, current, location_id)
        category = scoped_resource_or_404(db, MenuCategory, category_id, current, location_id=location_id)
        if category.items:
            raise HTTPException(status_code=409, detail="Move or delete category items first.")
        _audit(
            db,
            current=current,
            location=location,
            event_type="MENU_CATEGORY_DELETED",
            subject_type="MENU_CATEGORY",
            subject_id=category.id,
            before={"name": category.name},
        )
        db.delete(category)
        db.commit()

    @menu_router.get(f"{STAFF_PREFIX}/{{location_id}}/menu/items", response_model=list[MenuItemOut])
    def list_items(
        location_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.CHEF, StaffRole.BARTENDER)
        ),
    ) -> list[dict]:
        location = _location(db, current, location_id)
        query = _item_query().where(
            MenuItem.tenant_id == current.tenant_id,
            MenuItem.location_id == location_id,
        )
        if not _is_full_menu_admin(current):
            query = query.where(MenuItem.queue_destination.in_(_prep_destinations(current)))
        rows = db.scalars(query.order_by(MenuItem.category, MenuItem.name, MenuItem.id)).unique()
        return [_item_out(row, location) for row in rows]

    @menu_router.get(f"{STAFF_PREFIX}/{{location_id}}/menu/items/list", response_model=MenuItemListOut)
    def list_items_page(
        location_id: str,
        limit: int = 25,
        cursor: str | None = None,
        item_type: MenuItemType | None = None,
        available: bool | None = None,
        category_id: str | None = None,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.CHEF, StaffRole.BARTENDER)),
    ) -> dict:
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100.")
        location = _location(db, current, location_id)
        query = _item_query().where(MenuItem.tenant_id == current.tenant_id, MenuItem.location_id == location_id)
        if item_type is not None:
            query = query.where(MenuItem.item_type == item_type)
        if category_id is not None:
            query = query.where(MenuItem.category_id == category_id)
        if available is not None:
            query = query.where(MenuItem.available.is_(available))
        if not _is_full_menu_admin(current):
            query = query.where(MenuItem.queue_destination.in_(_prep_destinations(current)))
        values = decode_cursor(cursor)
        if values is not None:
            if len(values) != 3:
                raise HTTPException(status_code=422, detail="Invalid pagination cursor.")
            category, name, row_id = values
            query = query.where(or_(MenuItem.category > category, (MenuItem.category == category) & (MenuItem.name > name), (MenuItem.category == category) & (MenuItem.name == name) & (MenuItem.id > row_id)))
        rows = list(db.scalars(query.order_by(MenuItem.category, MenuItem.name, MenuItem.id).limit(limit + 1)).unique())
        page = page_payload(rows, limit=limit, cursor_for=lambda row: (row.category, row.name, row.id))
        page["items"] = [_item_out(row, location) for row in page["items"]]
        return page

    @menu_router.post(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items",
        response_model=MenuItemOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_item(
        location_id: str,
        payload: MenuItemCreateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.CHEF, StaffRole.BARTENDER)
        ),
    ) -> dict:
        location = _location(db, current, location_id)
        _assert_prep_create_access(current, payload)
        category = scoped_resource_or_404(
            db, MenuCategory, payload.category_id, current, location_id=location_id
        )
        if not category.is_active:
            raise HTTPException(status_code=409, detail="This menu category is inactive.")
        item = MenuItem(
            tenant_id=location.tenant_id,
            location_id=location.id,
            category=category.name,
            **payload.model_dump(),
        )
        db.add(item)
        db.flush()
        _audit(
            db,
            current=current,
            location=location,
            event_type="MENU_ITEM_CREATED",
            subject_type="MENU_ITEM",
            subject_id=item.id,
            after=payload.model_dump(mode="json"),
        )
        _stage_availability_event(
            db,
            location=location,
            resource_id=item.id,
            payload={"menu_item_id": item.id, "available": item.available, "change": "created"},
        )
        await commit_and_publish(db, active_bus)
        item = db.scalar(_item_query().where(MenuItem.id == item.id))
        assert item is not None
        return _item_out(item, location)

    @menu_router.patch(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}", response_model=MenuItemOut
    )
    async def update_item(
        location_id: str,
        item_id: str,
        payload: MenuItemUpdateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.CHEF, StaffRole.BARTENDER)
        ),
    ) -> dict:
        location = _location(db, current, location_id)
        item = scoped_resource_or_404(db, MenuItem, item_id, current, location_id=location_id)
        changes = payload.model_dump(exclude_unset=True)
        _assert_prep_update_access(current, item, changes)
        before = {key: str(getattr(item, key)) for key in changes}
        if payload.category_id:
            category = scoped_resource_or_404(
                db, MenuCategory, payload.category_id, current, location_id=location_id
            )
            if not category.is_active:
                raise HTTPException(status_code=409, detail="This menu category is inactive.")
            item.category = category.name
        for key, value in changes.items():
            setattr(item, key, value)
        _audit(
            db,
            current=current,
            location=location,
            event_type="MENU_ITEM_UPDATED",
            subject_type="MENU_ITEM",
            subject_id=item.id,
            before=before,
            after=payload.model_dump(mode="json", exclude_unset=True),
        )
        _stage_availability_event(
            db,
            location=location,
            resource_id=item.id,
            payload={"menu_item_id": item.id, "available": item.available, "change": "updated"},
        )
        try:
            await commit_and_publish(db, active_bus)
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="The menu item update conflicts with existing data.") from None
        item = db.scalar(_item_query().where(MenuItem.id == item.id))
        assert item is not None
        return _item_out(item, location)

    @menu_router.post(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}/sold-out",
        response_model=MenuItemOut,
    )
    async def set_sold_out(
        location_id: str,
        item_id: str,
        payload: SoldOutIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.CHEF, StaffRole.BARTENDER)
        ),
    ) -> dict:
        location = _location(db, current, location_id)
        item = scoped_resource_or_404(db, MenuItem, item_id, current, location_id=location_id)
        _assert_prep_item_access(current, item)
        before = {"sold_out_until": item.sold_out_until.isoformat() if item.sold_out_until else None}
        item.sold_out_until = payload.until if payload.sold_out else None
        item.sold_out_reason = payload.reason if payload.sold_out else None
        if payload.sold_out and payload.until is None:
            item.available = False
        elif not payload.sold_out:
            item.available = True
        _audit(
            db,
            current=current,
            location=location,
            event_type="MENU_AVAILABILITY_CHANGED",
            subject_type="MENU_ITEM",
            subject_id=item.id,
            before=before,
            after=payload.model_dump(mode="json"),
        )
        _stage_availability_event(
            db,
            location=location,
            resource_id=item.id,
            payload={"menu_item_id": item.id, "available": not payload.sold_out, "change": "sold_out"},
        )
        await commit_and_publish(db, active_bus)
        item = db.scalar(_item_query().where(MenuItem.id == item.id))
        assert item is not None
        return _item_out(item, location)

    @menu_router.delete(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_model=None,
    )
    async def delete_item(
        location_id: str,
        item_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> None:
        location = _location(db, current, location_id)
        item = scoped_resource_or_404(db, MenuItem, item_id, current, location_id=location_id)
        _audit(
            db,
            current=current,
            location=location,
            event_type="MENU_ITEM_DELETED",
            subject_type="MENU_ITEM",
            subject_id=item.id,
            before={"name": item.name},
        )
        _stage_availability_event(
            db,
            location=location,
            resource_id=item.id,
            payload={"menu_item_id": item.id, "available": False, "change": "deleted"},
        )
        db.delete(item)
        try:
            await commit_and_publish(db, active_bus)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="An ordered menu item cannot be deleted; mark it unavailable instead.",
            ) from None

    @menu_router.post(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}/modifier-groups",
        response_model=ModifierGroupOut,
        status_code=status.HTTP_201_CREATED,
    )
    def create_group(
        location_id: str,
        item_id: str,
        payload: ModifierGroupCreateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> dict:
        location = _location(db, current, location_id)
        item = scoped_resource_or_404(db, MenuItem, item_id, current, location_id=location_id)
        group = ModifierGroup(
            tenant_id=item.tenant_id,
            location_id=item.location_id,
            menu_item_id=item.id,
            **payload.model_dump(),
        )
        db.add(group)
        db.flush()
        _audit(db, current=current, location=location, event_type="MODIFIER_GROUP_CREATED", subject_type="MODIFIER_GROUP", subject_id=group.id, after=payload.model_dump(mode="json"))
        db.commit()
        return {**ModifierGroupOut.model_validate(group).model_dump(), "options": []}

    @menu_router.patch(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}/modifier-groups/{{group_id}}",
        response_model=ModifierGroupOut,
    )
    def update_group(
        location_id: str,
        item_id: str,
        group_id: str,
        payload: ModifierGroupUpdateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> ModifierGroup:
        location = _location(db, current, location_id)
        scoped_resource_or_404(db, MenuItem, item_id, current, location_id=location_id)
        group = scoped_resource_or_404(db, ModifierGroup, group_id, current, location_id=location_id)
        if group.menu_item_id != item_id:
            raise HTTPException(status_code=404, detail="Resource not found.")
        changes = payload.model_dump(exclude_unset=True)
        minimum = changes.get("minimum_selections", group.minimum_selections)
        maximum = changes.get("maximum_selections", group.maximum_selections)
        if maximum < minimum:
            raise HTTPException(status_code=422, detail="maximum_selections must be at least minimum_selections.")
        before = {key: getattr(group, key) for key in changes}
        for key, value in changes.items():
            setattr(group, key, value)
        _audit(db, current=current, location=location, event_type="MODIFIER_GROUP_UPDATED", subject_type="MODIFIER_GROUP", subject_id=group.id, before=before, after=payload.model_dump(mode="json", exclude_unset=True))
        db.commit()
        return group

    @menu_router.delete(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}/modifier-groups/{{group_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_model=None,
    )
    def delete_group(
        location_id: str,
        item_id: str,
        group_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> None:
        location = _location(db, current, location_id)
        group = scoped_resource_or_404(db, ModifierGroup, group_id, current, location_id=location_id)
        if group.menu_item_id != item_id:
            raise HTTPException(status_code=404, detail="Resource not found.")
        for option in list(group.options):
            db.delete(option)
        _audit(db, current=current, location=location, event_type="MODIFIER_GROUP_DELETED", subject_type="MODIFIER_GROUP", subject_id=group.id, before={"name": group.name})
        db.delete(group)
        db.commit()

    @menu_router.post(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}/modifier-groups/{{group_id}}/options",
        response_model=ModifierOptionOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_option(
        location_id: str,
        item_id: str,
        group_id: str,
        payload: ModifierOptionCreateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> dict:
        location = _location(db, current, location_id)
        group = scoped_resource_or_404(db, ModifierGroup, group_id, current, location_id=location_id)
        if group.menu_item_id != item_id:
            raise HTTPException(status_code=404, detail="Resource not found.")
        option = ModifierOption(
            tenant_id=location.tenant_id,
            location_id=location.id,
            menu_item_id=item_id,
            group_id=group.id,
            **payload.model_dump(),
        )
        db.add(option)
        db.flush()
        _audit(db, current=current, location=location, event_type="MENU_AVAILABILITY_CHANGED", subject_type="MODIFIER_OPTION", subject_id=option.id, after=payload.model_dump(mode="json"))
        _stage_availability_event(db, location=location, resource_id=option.id, payload={"modifier_option_id": option.id, "available": option.available, "change": "created"})
        await commit_and_publish(db, active_bus)
        return {
            **payload.model_dump(),
            "id": option.id,
            "final_price_delta": all_in_component_price(Decimal(option.price_delta), vat_rate=Decimal(location.vat_rate), service_charge_rate=Decimal(location.service_charge_rate)),
        }

    @menu_router.patch(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}/modifier-options/{{option_id}}",
        response_model=ModifierOptionOut,
    )
    async def update_option(
        location_id: str,
        item_id: str,
        option_id: str,
        payload: ModifierOptionUpdateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> dict:
        location = _location(db, current, location_id)
        option = scoped_resource_or_404(db, ModifierOption, option_id, current, location_id=location_id)
        if option.menu_item_id != item_id:
            raise HTTPException(status_code=404, detail="Resource not found.")
        changes = payload.model_dump(exclude_unset=True)
        before = {key: str(getattr(option, key)) for key in changes}
        for key, value in changes.items():
            setattr(option, key, value)
        _audit(db, current=current, location=location, event_type="MENU_AVAILABILITY_CHANGED", subject_type="MODIFIER_OPTION", subject_id=option.id, before=before, after=payload.model_dump(mode="json", exclude_unset=True))
        _stage_availability_event(db, location=location, resource_id=option.id, payload={"modifier_option_id": option.id, "available": option.available, "change": "updated"})
        await commit_and_publish(db, active_bus)
        return {
            "id": option.id,
            "name": option.name,
            "price_delta": option.price_delta,
            "final_price_delta": all_in_component_price(Decimal(option.price_delta), vat_rate=Decimal(location.vat_rate), service_charge_rate=Decimal(location.service_charge_rate)),
            "available": option.available,
            "sort_order": option.sort_order,
        }

    @menu_router.delete(
        f"{STAFF_PREFIX}/{{location_id}}/menu/items/{{item_id}}/modifier-options/{{option_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_model=None,
    )
    async def delete_option(
        location_id: str,
        item_id: str,
        option_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)),
    ) -> None:
        location = _location(db, current, location_id)
        option = scoped_resource_or_404(db, ModifierOption, option_id, current, location_id=location_id)
        if option.menu_item_id != item_id:
            raise HTTPException(status_code=404, detail="Resource not found.")
        _audit(db, current=current, location=location, event_type="MENU_AVAILABILITY_CHANGED", subject_type="MODIFIER_OPTION", subject_id=option.id, before={"name": option.name, "available": option.available})
        _stage_availability_event(db, location=location, resource_id=option.id, payload={"modifier_option_id": option.id, "available": False, "change": "deleted"})
        db.delete(option)
        await commit_and_publish(db, active_bus)

    @menu_router.get(f"{PUBLIC_PREFIX}/{{qr_token}}", response_model=PublicMenuOut)
    def public_menu(qr_token: str, db: Session = Depends(get_db)) -> dict:
        try:
            _, table, location = resolve_table_qr(db, qr_token)
        except InvalidTableQr as exc:
            raise HTTPException(status_code=410 if exc.expired else 404, detail=str(exc)) from None
        location = db.scalar(
            select(Location)
            .options(selectinload(Location.operating_hours))
            .where(Location.id == location.id, Location.tenant_id == location.tenant_id)
        )
        assert location is not None
        rows = db.scalars(
            _item_query().where(
                MenuItem.tenant_id == location.tenant_id,
                MenuItem.location_id == location.id,
            ).order_by(MenuItem.category, MenuItem.name, MenuItem.id)
        ).unique()
        menu = [
            _item_out(row, location)
            for row in rows
            if row.menu_category is None or row.menu_category.is_active
        ]
        return {
            "table_id": table.id,
            "table_label": table.label,
            "location_id": location.id,
            "location_name": location.name,
            "timezone": location.timezone,
            "currency": location.currency,
            "currently_open": location_is_currently_open(location),
            "manual_ordering_open": location.is_open,
            "vat_rate": location.vat_rate,
            "service_charge_rate": location.service_charge_rate,
            "charge_disclosure": "Displayed prices include VAT and service charge.",
            "operating_hours": [
                {
                    "weekday": row.weekday,
                    "opens_at": row.opens_at.isoformat() if row.opens_at else None,
                    "closes_at": row.closes_at.isoformat() if row.closes_at else None,
                    "is_closed": row.is_closed,
                }
                for row in sorted(location.operating_hours, key=lambda item: item.weekday)
            ],
            "menu": menu,
        }

    @menu_router.post(
        f"{PUBLIC_PREFIX}/{{qr_token}}/menu/validate",
        response_model=MenuSelectionOut,
    )
    def validate_public_selection(
        qr_token: str,
        payload: MenuSelectionIn,
        db: Session = Depends(get_db),
    ) -> dict:
        try:
            _, _, location = resolve_table_qr(db, qr_token)
        except InvalidTableQr as exc:
            raise HTTPException(status_code=410 if exc.expired else 404, detail=str(exc)) from None
        try:
            selection = validate_menu_selection(
                db,
                tenant_id=location.tenant_id,
                location_id=location.id,
                menu_item_id=payload.menu_item_id,
                modifier_option_ids=payload.modifier_option_ids,
            )
        except MenuSelectionError as exc:
            raise HTTPException(status_code=409 if exc.unavailable else 422, detail=str(exc)) from None
        item = db.scalar(_item_query().where(MenuItem.id == selection.item.id))
        assert item is not None
        breakdown = price_breakdown(
            base_price=Decimal(item.base_price),
            modifier_prices=[Decimal(option.price_delta) for option in selection.options],
            quantity=payload.quantity,
            vat_rate=Decimal(location.vat_rate),
            service_charge_rate=Decimal(location.service_charge_rate),
        )
        return {
            "item": _item_out(item, location),
            "selected_modifier_ids": [option.id for option in selection.options],
            "pricing": {
                "item_subtotal": breakdown.item_subtotal,
                "modifier_subtotal": breakdown.modifier_subtotal,
                "subtotal": breakdown.subtotal,
                "vat": breakdown.vat,
                "service_charge": breakdown.service_charge,
                "total": breakdown.total,
                "currency": location.currency,
            },
        }

    return menu_router


router = create_menu_router()
