from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MYSQL_TABLE_ARGS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def utc_now_naive() -> datetime:
    """Return a timezone-naive UTC datetime suitable for MySQL DATETIME columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalize naive MySQL DATETIME values as timezone-aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
