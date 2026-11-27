from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class WebsiteUrlRule(TimestampMixin, Base):
    __tablename__ = "website_url_rules"
    __table_args__ = (
        Index("ix_website_url_rules_site_prio", "website_id", "is_enabled", "priority"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "websites.id",
            name="fk_wur_website_id_websites",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    target_content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    match_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="glob",
        server_default="glob",
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default=text("100"),
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
