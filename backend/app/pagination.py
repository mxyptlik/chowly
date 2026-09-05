"""Small, stable cursor pagination primitives for collection endpoints."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import HTTPException


def decode_cursor(cursor: str | None) -> tuple[Any, ...] | None:
    if not cursor:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        if not isinstance(value, list):
            raise ValueError
        return tuple(value)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor.") from exc


def encode_cursor(*values: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, separators=(",", ":")).encode("utf-8")).decode("ascii")


def page_payload(items: list[Any], *, limit: int, cursor_for: callable) -> dict[str, Any]:
    has_more = len(items) > limit
    visible = items[:limit]
    return {
        "items": visible,
        "next_cursor": encode_cursor(*cursor_for(visible[-1])) if has_more and visible else None,
        "has_more": has_more,
    }
