"""Cursor pagination helpers.

Cursors are opaque base64 values of ``<iso-timestamp>|<uuid>``. Keyset pagination
keeps queries bounded and stable while new rows are written.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime
from typing import Any

from app.core.errors import ValidationFailed


def encode_cursor(timestamp: datetime, row_id: uuid.UUID) -> str:
    raw = f"{timestamp.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        ts_raw, id_raw = raw.split("|", 1)
        return datetime.fromisoformat(ts_raw), uuid.UUID(id_raw)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationFailed("invalid pagination cursor") from exc


def paginate(
    session,
    model: Any,
    *,
    filters: list,
    order_column,
    limit: int,
    cursor: str | None,
    id_column=None,
):
    """Return ``(rows, next_cursor)`` for a descending keyset pagination query."""
    id_column = id_column if id_column is not None else model.id
    query = session.query(model).filter(*filters)
    if cursor:
        ts, row_id = decode_cursor(cursor)
        query = query.filter((order_column < ts) | ((order_column == ts) & (id_column < row_id)))
    rows = query.order_by(order_column.desc(), id_column.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(order_column_value(rows[-1], order_column), rows[-1].id) if has_more else None
    return rows, next_cursor


def order_column_value(row: Any, order_column) -> datetime:
    key = getattr(order_column, "key", None) or "created_at"
    return getattr(row, key)


__all__ = ["encode_cursor", "decode_cursor", "paginate"]
