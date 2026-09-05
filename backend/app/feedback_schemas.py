"""Transport contracts for post-service ratings and private complaints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ComplaintStatus


class _FeedbackText(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2_000)

    @field_validator("comment")
    @classmethod
    def empty_comment_is_none(cls, value: str | None) -> str | None:
        return value or None


class ItemRatingIn(_FeedbackText):
    order_line_id: str = Field(min_length=1, max_length=36)


class OrderRatingIn(_FeedbackText):
    pass


class RatingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    order_line_id: str | None = None
    score: int
    comment: str | None
    created_at: datetime
    complaint_prompt: bool
    complaint_prompt_message: str | None = None


class ComplaintCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=5_000)
    order_rating_id: str | None = Field(default=None, max_length=36)
    item_rating_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def only_one_rating_context(self) -> "ComplaintCreateIn":
        if self.order_rating_id and self.item_rating_id:
            raise ValueError("A complaint may reference either an order rating or an item rating, not both.")
        return self


class ComplaintResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resolution_note: str = Field(min_length=1, max_length=5_000)
    disposition: Literal["RESOLVED", "DISMISSED"] = "RESOLVED"


class ComplaintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    location_id: str
    order_id: str
    order_rating_id: str | None
    item_rating_id: str | None
    order_line_id: str | None = None
    subject: str
    detail: str
    status: ComplaintStatus
    resolution_note: str | None
    resolved_by_id: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ComplaintListOut(BaseModel):
    complaints: list[ComplaintOut]

