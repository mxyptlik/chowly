"""Location table administration, activity projection, and renewable QR endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from app.models import AuditEvent, DiningTable, Location, StaffRole
from app.qr_service import calculate_table_activity, issue_table_qr
from app.realtime import RedisEventBus
from app.pagination import decode_cursor, page_payload
from app.table_schemas import QrPresentationOut, TableCreateIn, TableListOut, TableOut, TableUpdateIn


EVENT_ROLES = (StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.WAITER)


def _location(db: Session, current: CurrentStaff, location_id: str) -> Location:
    assert_location_access(current, location_id)
    location = db.scalar(
        select(Location).where(
            Location.id == location_id,
            Location.tenant_id == current.tenant_id,
        )
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return location


def _out(db: Session, table: DiningTable) -> dict:
    return {
        "id": table.id,
        "location_id": table.location_id,
        "label": table.label,
        "capacity": table.capacity,
        "is_enabled": table.is_enabled,
        "is_active": calculate_table_activity(db, table),
    }


def _audit(
    db: Session,
    *,
    current: CurrentStaff,
    table: DiningTable,
    event_type: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=table.tenant_id,
            location_id=table.location_id,
            actor_id=current.staff_id,
            event_type=event_type,
            subject_type="TABLE",
            subject_id=table.id,
            before_data=before,
            after_data=after,
        )
    )


def _stage_table_event(db: Session, table: DiningTable, payload: dict) -> None:
    draft = EventDraft(
        type=EventType.TABLE_CHANGED,
        scope=EventScope(tenant_id=table.tenant_id, location_id=table.location_id),
        resource=EventResource(kind=ResourceKind.TABLE, id=table.id),
        payload=payload,
    )
    for role in EVENT_ROLES:
        stage_domain_event(
            db,
            staff_channel(table.tenant_id, table.location_id, role.value),
            draft,
        )


def create_tables_router(event_bus: EventBus | None = None) -> APIRouter:
    active_bus = event_bus or RedisEventBus(get_settings().redis_url)
    table_router = APIRouter(prefix="/api/v1/staff/locations", tags=["tables"])

    @table_router.get("/{location_id}/tables", response_model=list[TableOut])
    def list_tables(
        location_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.WAITER)
        ),
    ) -> list[dict]:
        _location(db, current, location_id)
        rows = db.scalars(
            select(DiningTable)
            .where(
                DiningTable.tenant_id == current.tenant_id,
                DiningTable.location_id == location_id,
            )
            .order_by(DiningTable.label, DiningTable.id)
        )
        return [_out(db, row) for row in rows]

    @table_router.get("/{location_id}/tables/list", response_model=TableListOut)
    def list_tables_page(
        location_id: str,
        limit: int = 25,
        cursor: str | None = None,
        enabled: bool | None = None,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.WAITER)),
    ) -> dict:
        """Cursor-paginated table collection; the legacy list remains unchanged."""
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100.")
        _location(db, current, location_id)
        query = select(DiningTable).where(DiningTable.tenant_id == current.tenant_id, DiningTable.location_id == location_id)
        if enabled is not None:
            query = query.where(DiningTable.is_enabled.is_(enabled))
        values = decode_cursor(cursor)
        if values is not None:
            if len(values) != 2:
                raise HTTPException(status_code=422, detail="Invalid pagination cursor.")
            label, row_id = values
            query = query.where(or_(DiningTable.label > label, (DiningTable.label == label) & (DiningTable.id > row_id)))
        rows = list(db.scalars(query.order_by(DiningTable.label, DiningTable.id).limit(limit + 1)))
        page = page_payload(rows, limit=limit, cursor_for=lambda row: (row.label, row.id))
        page["items"] = [_out(db, row) for row in page["items"]]
        return page

    @table_router.post(
        "/{location_id}/tables",
        response_model=TableOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_table(
        location_id: str,
        payload: TableCreateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)
        ),
    ) -> dict:
        location = _location(db, current, location_id)
        table = DiningTable(
            tenant_id=location.tenant_id,
            location_id=location.id,
            **payload.model_dump(),
        )
        db.add(table)
        try:
            db.flush()
            _audit(
                db,
                current=current,
                table=table,
                event_type="TABLE_CREATED",
                after=payload.model_dump(mode="json"),
            )
            _stage_table_event(db, table, {"change": "created", "label": table.label})
            await commit_and_publish(db, active_bus)
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="This table label already exists.") from None
        return _out(db, table)

    @table_router.patch("/{location_id}/tables/{table_id}", response_model=TableOut)
    async def update_table(
        location_id: str,
        table_id: str,
        payload: TableUpdateIn,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)
        ),
    ) -> dict:
        _location(db, current, location_id)
        table = scoped_resource_or_404(
            db, DiningTable, table_id, current, location_id=location_id
        )
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("is_enabled") is False and calculate_table_activity(db, table):
            raise HTTPException(status_code=409, detail="An active table cannot be disabled.")
        before = {key: getattr(table, key) for key in changes}
        for key, value in changes.items():
            setattr(table, key, value)
        _audit(
            db,
            current=current,
            table=table,
            event_type="TABLE_UPDATED",
            before=before,
            after=payload.model_dump(mode="json", exclude_unset=True),
        )
        _stage_table_event(db, table, {"change": "updated", **payload.model_dump(mode="json", exclude_unset=True)})
        try:
            await commit_and_publish(db, active_bus)
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="The table update conflicts with existing data.") from None
        return _out(db, table)

    @table_router.delete(
        "/{location_id}/tables/{table_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_model=None,
    )
    async def disable_table(
        location_id: str,
        table_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER)
        ),
    ) -> None:
        _location(db, current, location_id)
        table = scoped_resource_or_404(
            db, DiningTable, table_id, current, location_id=location_id
        )
        if calculate_table_activity(db, table):
            raise HTTPException(status_code=409, detail="An active table cannot be disabled.")
        table.is_enabled = False
        _audit(
            db,
            current=current,
            table=table,
            event_type="TABLE_DISABLED",
            before={"is_enabled": True},
            after={"is_enabled": False},
        )
        _stage_table_event(db, table, {"change": "disabled", "is_enabled": False})
        await commit_and_publish(db, active_bus)

    def qr_payload(table: DiningTable, issued) -> dict:
        origin = get_settings().cors_origin_list[0].rstrip("/")
        menu_url = f"{origin}/dine/{issued.raw_token}"
        return {
            "table_id": table.id,
            "table_label": table.label,
            "issued_on": issued.row.issued_on,
            "issued_at": issued.row.issued_at,
            "expires_at": issued.expires_at,
            "menu_url": menu_url,
            "qr_value": menu_url,
            "presentation": "DIGITAL",
            "printable": True,
            "print_label": f"{table.label} · Scan to view menu",
        }

    @table_router.get("/{location_id}/tables/{table_id}/qr", response_model=QrPresentationOut)
    async def get_daily_qr(
        location_id: str,
        table_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.WAITER)
        ),
    ) -> dict:
        location = _location(db, current, location_id)
        table = scoped_resource_or_404(
            db, DiningTable, table_id, current, location_id=location_id
        )
        if not table.is_enabled:
            raise HTTPException(status_code=409, detail="Enable this table before issuing a QR code.")
        issued = issue_table_qr(
            db,
            table=table,
            location=location,
            secret=get_settings().session_signing_secret,
            generated_by_id=current.staff_id,
        )
        if issued.created:
            _audit(
                db,
                current=current,
                table=table,
                event_type="TABLE_QR_DAILY_ISSUED",
                after={"issued_on": issued.row.issued_on.isoformat()},
            )
            _stage_table_event(
                db,
                table,
                {"change": "qr_daily_issued", "issued_on": issued.row.issued_on.isoformat()},
            )
            await commit_and_publish(db, active_bus)
        return qr_payload(table, issued)

    @table_router.post("/{location_id}/tables/{table_id}/qr/regenerate", response_model=QrPresentationOut)
    async def regenerate_qr(
        location_id: str,
        table_id: str,
        db: Session = Depends(get_db),
        current: CurrentStaff = Depends(
            require_roles(StaffRole.TENANT_OWNER, StaffRole.MANAGER, StaffRole.WAITER)
        ),
    ) -> dict:
        location = _location(db, current, location_id)
        table = scoped_resource_or_404(
            db, DiningTable, table_id, current, location_id=location_id
        )
        if not table.is_enabled:
            raise HTTPException(status_code=409, detail="Enable this table before issuing a QR code.")
        issued = issue_table_qr(
            db,
            table=table,
            location=location,
            secret=get_settings().session_signing_secret,
            generated_by_id=current.staff_id,
            force=True,
        )
        _audit(
            db,
            current=current,
            table=table,
            event_type="TABLE_QR_REGENERATED",
            after={"issued_on": issued.row.issued_on.isoformat()},
        )
        _stage_table_event(
            db,
            table,
            {"change": "qr_regenerated", "issued_on": issued.row.issued_on.isoformat()},
        )
        await commit_and_publish(db, active_bus)
        return qr_payload(table, issued)

    return table_router


router = create_tables_router()
