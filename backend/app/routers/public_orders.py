"""Token-protected public ordering endpoints without customer authentication."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.events import EventBus, commit_and_publish
from app.order_schemas import (
    PublicCancelIn,
    PublicOrderCreateIn,
    PublicOrderCreatedOut,
    PublicOrderOut,
    PublicServiceModeIn,
)
from app.order_service import (
    OrderDomainError,
    cancel_public_order,
    create_public_order,
    issue_order_realtime_token,
    public_order_or_404,
    public_order_payload,
    raise_order_http,
    switch_public_service_mode,
)
from app.realtime import RedisEventBus


def _token(request: Request, header_token: str | None = None) -> str | None:
    return header_token or request.query_params.get("access_token")


def create_public_orders_router(event_bus: EventBus | None = None) -> APIRouter:
    settings = get_settings()
    bus = event_bus or RedisEventBus(
        settings.redis_url, history_limit=settings.event_history_limit
    )
    router = APIRouter(prefix="/api/v1/public", tags=["public orders"])

    @router.post(
        "/tables/{qr_token}/orders",
        response_model=PublicOrderCreatedOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def submit_order(
        qr_token: str,
        payload: PublicOrderCreateIn,
        db: Session = Depends(get_db),
    ) -> dict:
        try:
            order, raw_token = create_public_order(
                db,
                qr_token=qr_token,
                customer=payload.customer,
                service_mode=payload.service_mode,
                lines=payload.lines,
            )
            await commit_and_publish(db, bus)
            return {
                **public_order_payload(db, order),
                "access_token": raw_token,
                "realtime_token": issue_order_realtime_token(order.id),
            }
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.get("/orders/{order_id}", response_model=PublicOrderOut)
    def order_status(
        order_id: str,
        request: Request,
        access_header: str | None = Header(default=None, alias="X-Order-Access-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        try:
            order = public_order_or_404(db, order_id, _token(request, access_header))
            return public_order_payload(db, order)
        except OrderDomainError as error:
            raise_order_http(error)

    @router.post("/orders/{order_id}/realtime-grant")
    def order_realtime_grant(
        order_id: str,
        request: Request,
        access_header: str | None = Header(default=None, alias="X-Order-Access-Token"),
        db: Session = Depends(get_db),
    ) -> dict[str, str]:
        try:
            public_order_or_404(db, order_id, _token(request, access_header))
            return {"token": issue_order_realtime_token(order_id)}
        except OrderDomainError as error:
            raise_order_http(error)

    @router.patch("/orders/{order_id}/service-mode", response_model=PublicOrderOut)
    async def switch_mode(
        order_id: str,
        payload: PublicServiceModeIn,
        request: Request,
        access_header: str | None = Header(default=None, alias="X-Order-Access-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        try:
            order = public_order_or_404(db, order_id, _token(request, access_header))
            switch_public_service_mode(
                db,
                order=order,
                service_mode=payload.service_mode,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return public_order_payload(db, order)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    @router.post("/orders/{order_id}/cancel", response_model=PublicOrderOut)
    async def cancel_order(
        order_id: str,
        payload: PublicCancelIn,
        request: Request,
        access_header: str | None = Header(default=None, alias="X-Order-Access-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        try:
            order = public_order_or_404(db, order_id, _token(request, access_header))
            cancel_public_order(
                db,
                order=order,
                reason=payload.reason,
                expected_version=payload.expected_version,
            )
            await commit_and_publish(db, bus)
            return public_order_payload(db, order)
        except OrderDomainError as error:
            db.rollback()
            raise_order_http(error)

    return router


router = create_public_orders_router()
