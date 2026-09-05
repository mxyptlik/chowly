"""Stable API contracts for location-scoped operational reports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReportDateRange(BaseModel):
    start_date: date
    end_date: date
    start_utc: datetime
    end_utc_exclusive: datetime


class DailyReportRow(BaseModel):
    date: date
    order_count: int = 0
    paid_order_count: int = 0
    gross_revenue: Decimal = Decimal("0.00")
    refund_total: Decimal = Decimal("0.00")
    net_revenue: Decimal = Decimal("0.00")


class OrderReport(BaseModel):
    total: int = 0
    paid_orders: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    gross_revenue: Decimal = Decimal("0.00")
    refund_total: Decimal = Decimal("0.00")
    net_revenue: Decimal = Decimal("0.00")


class PaymentMethodReport(BaseModel):
    method: str
    attempt_count: int = 0
    successful_count: int = 0
    successful_amount: Decimal = Decimal("0.00")


class PaymentStatusReport(BaseModel):
    status: str
    count: int = 0
    amount: Decimal = Decimal("0.00")


class RefundReport(BaseModel):
    attempt_count: int = 0
    successful_count: int = 0
    successful_total: Decimal = Decimal("0.00")
    by_status: dict[str, int] = Field(default_factory=dict)


class PaymentsReport(BaseModel):
    total_attempts: int = 0
    methods: list[PaymentMethodReport] = Field(default_factory=list)
    statuses: list[PaymentStatusReport] = Field(default_factory=list)
    refunds: RefundReport = Field(default_factory=RefundReport)


class DurationMetric(BaseModel):
    sample_count: int = 0
    average_minutes: Decimal = Decimal("0.00")


class WaitTimesReport(BaseModel):
    acceptance: DurationMetric = Field(default_factory=DurationMetric)
    preparation: DurationMetric = Field(default_factory=DurationMetric)
    ready_to_serve: DurationMetric = Field(default_factory=DurationMetric)
    total: DurationMetric = Field(default_factory=DurationMetric)


class TopItemReport(BaseModel):
    item_name: str
    quantity: int
    paid_revenue: Decimal


class CancellationReport(BaseModel):
    total: int = 0
    by_actor: dict[str, int] = Field(default_factory=dict)
    by_stage: dict[str, int] = Field(default_factory=dict)
    by_reason: dict[str, int] = Field(default_factory=dict)


class ComplaintReport(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    resolved_count: int = 0
    average_resolution_hours: Decimal = Decimal("0.00")


class RatingMetric(BaseModel):
    count: int = 0
    average: Decimal = Decimal("0.00")
    distribution: dict[str, int] = Field(default_factory=dict)


class RatingsReport(BaseModel):
    orders: RatingMetric = Field(default_factory=RatingMetric)
    items: RatingMetric = Field(default_factory=RatingMetric)


class OperationsReport(BaseModel):
    location_id: str
    currency: str
    timezone: str
    date_range: ReportDateRange
    daily: list[DailyReportRow]
    orders: OrderReport
    payments: PaymentsReport
    wait_times: WaitTimesReport
    top_items: list[TopItemReport]
    cancellations: CancellationReport
    complaints: ComplaintReport
    ratings: RatingsReport
