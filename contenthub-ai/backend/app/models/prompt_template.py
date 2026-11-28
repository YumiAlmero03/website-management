from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin, utc_now_naive


class PromptTemplate(TimestampMixin, Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("template_key", "scope_key", name="uq_prompt_templates_key_scope"),
        Index("ix_prompt_templates_task_platform", "task_type", "platform_key", "is_active"),
        Index("ix_prompt_templates_website", "website_id"),
        Index("ix_prompt_templates_social_profile", "social_profile_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_key: Mapped[str] = mapped_column(
        String(120), nullable=False, default="global", server_default="global"
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    platform_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_prompt_templates_website_id", ondelete="CASCADE"),
        nullable=True,
    )
    social_profile_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "social_profiles.id",
            name="fk_prompt_templates_social_profile_id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    system_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    available_variables_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    response_schema_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    is_system_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )


class PromptTemplateRevision(Base):
    __tablename__ = "prompt_template_revisions"
    __table_args__ = (
        UniqueConstraint("prompt_template_id", "version", name="uq_prompt_template_revs_ver"),
        Index("ix_prompt_template_revs_tpl", "prompt_template_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prompt_template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "prompt_templates.id",
            name="fk_prompt_template_revs_template_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_prompt_template_revs_created_by", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        default=utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
