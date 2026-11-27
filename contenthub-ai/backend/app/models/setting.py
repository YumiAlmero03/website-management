from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class ApplicationSetting(TimestampMixin, Base):
    __tablename__ = "application_settings"
    __table_args__ = (
        UniqueConstraint("setting_key", name="uq_application_settings_setting_key"),
        Index("ix_application_settings_category", "category"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_secret: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "users.id", name="fk_application_settings_updated_by_users", ondelete="SET NULL"
        ),
        nullable=True,
    )
