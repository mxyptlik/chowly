"""Transport contracts for payments, refunds, and digital receipts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import PaymentMethod, PaymentStatus, ReceiptDeliveryStatus, RefundStatus


class OnlinePaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal[PaymentMethod.CARD, PaymentMethod.TRANSFER, PaymentMethod.WALLET]
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    mock_scenario: Literal["APPROVED", "DECLINED", "TEMPORARY_FAILURE"] = "APPROVED"

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class CashPaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class RefundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("A meaningful refund reason is required.")
        return cleaned


class PaymentAttemptOut(BaseModel):
    id: str
    order_id: str
    method: PaymentMethod
    amount: Decimal
    currency: str
    status: PaymentStatus
    reference: str
    provider_code: str | None
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None
    duplicate: bool = False


class RefundOut(BaseModel):
    id: str
    order_id: str
    payment_attempt_id: str
    amount: Decimal
    currency: str
    reason: str
    status: RefundStatus
    reference: str
    created_at: datetime
    completed_at: datetime | None
    duplicate: bool = False


class ReceiptDeliveryOut(BaseModel):
    """Internal delivery state without the diner's receipt or contact details."""

    id: str
    receipt_number: str
    issued_at: datetime
    delivery_status: ReceiptDeliveryStatus
    delivery_attempts: int
    delivered_at: datetime | None


class StaffPaymentDetailsOut(BaseModel):
    """Manager/owner operational payment view for one location-scoped order."""

    order_id: str
    payment_attempts: list[PaymentAttemptOut]
    refunds: list[RefundOut]
    receipt_delivery: ReceiptDeliveryOut | None


class ReceiptOut(BaseModel):
    id: str
    receipt_number: str
    order_id: str
    issued_at: datetime
    delivery_status: ReceiptDeliveryStatus
    delivery_attempts: int
    refunded: bool
    payload: dict
    html: str
