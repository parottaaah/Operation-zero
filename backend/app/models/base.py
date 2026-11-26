"""Shared model base, mixins and enum helpers."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Portable enum column: stored as VARCHAR so SQLite and Postgres agree."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=40,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def utcnow() -> datetime:
    """Naive UTC now. All timestamps in the database are stored as UTC."""
    return datetime.utcnow()


class TimestampMixin:
    # Python-side defaults keep microsecond precision consistent across rows. The
    # server default remains for raw SQL inserts.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utcnow,
        server_default=func.now(),
        onupdate=utcnow,
        nullable=False,
    )


__all__ = ["Base", "enum_column", "UUIDMixin", "TimestampMixin", "utcnow"]
