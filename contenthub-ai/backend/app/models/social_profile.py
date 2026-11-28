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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, TimestampMixin


class SocialProfile(TimestampMixin, Base):
    __tablename__ = "social_profiles"
    __table_args__ = (
        Index("ix_social_profiles_website_active", "website_id", "is_active"),
        Index("ix_social_profiles_website_platform", "website_id", "platform_id"),
        Index("ix_social_profiles_generation", "website_id", "is_active", "generation_enabled"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    website_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("websites.id", name="fk_social_profiles_website_id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("platforms.id", name="fk_social_profiles_platform_id", ondelete="RESTRICT"),
        nullable=False,
    )

    # General information
    profile_name: Mapped[str] = mapped_column(String(150), nullable=False)
    profile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )

    # Publishing & Generation Preferences (external auto-publishing stays disabled in Phase 3)
    publishing_method: Mapped[str] = mapped_column(
        String(24), nullable=False, default="manual", server_default="manual"
    )
    credential_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_configured", server_default="not_configured"
    )
    generation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    automatic_generation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    auto_publish_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )

    # AI Configuration
    custom_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    writing_tone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    platform_ai_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_hashtags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    default_cta: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_length: Mapped[str | None] = mapped_column(String(32), nullable=True)
    character_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    include_source_url: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    include_hashtags: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    include_emojis: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    content_restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fernet-encrypted credentials (never serialized directly to frontend API or AI prompts)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_api_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_app_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_app_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    credentials_updated_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
