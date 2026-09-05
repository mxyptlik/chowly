from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class TableCreateIn(BaseModel):
    label: str = Field(min_length=1, max_length=30)
    capacity: int = Field(ge=1, le=100)
    is_enabled: bool = True


class TableUpdateIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=30)
    capacity: int | None = Field(default=None, ge=1, le=100)
    is_enabled: bool | None = None


class TableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    location_id: str
    label: str
    capacity: int
    is_enabled: bool
    is_active: bool


class TableListOut(BaseModel):
    items: list[TableOut]
    next_cursor: str | None = None
    has_more: bool


class QrPresentationOut(BaseModel):
    table_id: str
    table_label: str
    issued_on: date
    issued_at: datetime
    expires_at: datetime
    menu_url: str
    qr_value: str
    presentation: str = "DIGITAL"
    printable: bool = True
    print_label: str
