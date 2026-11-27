from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables and .env files."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "ContentHub AI"
    app_version: str = "0.1.0"
    app_env: str = "development"
    app_debug: bool = False
    app_timezone: str = "Asia/Manila"
    app_url: str = "http://127.0.0.1:3100"
    api_base_url: str = "http://127.0.0.1:8100"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8100
    cors_origins: str = "http://127.0.0.1:3100,http://localhost:3100"

    # Security & Encryption
    app_secret_key: str = ""
    app_encryption_key: str = ""
    session_cookie_name: str = "contenthub_session"
    session_ttl_minutes: int = Field(default=720, ge=15, le=43200)
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"
    login_rate_limit_max_attempts: int = Field(default=5, ge=1, le=50)
    login_rate_limit_window_seconds: int = Field(default=900, ge=30, le=86400)

    # MySQL (existing aaPanel service; never use root at runtime)
    db_host: str = "127.0.0.1"
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_name: str = "contenthub_ai"
    db_user: str = "contenthub_user"
    db_password: str = ""
    db_pool_size: int = Field(default=3, ge=1, le=20)
    db_max_overflow: int = Field(default=2, ge=0, le=20)
    db_pool_recycle: int = Field(default=1800, ge=60, le=86400)
    db_connect_timeout: int = Field(default=5, ge=1, le=60)

    # Optional isolated test MySQL URL
    contenthub_test_database_url: str = ""

    # Persistent storage
    storage_root: str = "./storage"

    # Resource Guardian defaults
    resource_cpu_warning_percent: float = Field(default=65.0, ge=10.0, le=100.0)
    resource_cpu_critical_percent: float = Field(default=85.0, ge=10.0, le=100.0)
    resource_ram_warning_percent: float = Field(default=75.0, ge=10.0, le=100.0)
    resource_load_avg_threshold: float = Field(default=12.0, ge=0.5, le=128.0)
    resource_max_concurrent_generation: int = Field(default=1, ge=1, le=10)
    resource_max_concurrent_browsers: int = Field(default=1, ge=1, le=4)
    resource_recheck_interval_minutes: int = Field(default=5, ge=1, le=60)

    # Phase 2 — Website Scanner, SSRF Security, Content & Media
    scanner_user_agent: str = "ContentHubAI/0.2 (+self-hosted-website-monitor)"
    scanner_request_timeout_seconds: float = Field(default=15.0, ge=2.0, le=120.0)
    scanner_crawl_delay_seconds: float = Field(default=0.5, ge=0.0, le=30.0)
    scanner_max_urls_per_scan: int = Field(default=100, ge=1, le=1000)
    scanner_max_response_bytes: int = Field(default=5_242_880, ge=65_536, le=26_214_400)
    scanner_max_redirects: int = Field(default=5, ge=0, le=10)
    scanner_max_sitemap_depth: int = Field(default=3, ge=1, le=6)
    scanner_max_sitemap_files: int = Field(default=25, ge=1, le=100)
    scanner_max_decompressed_bytes: int = Field(default=20_971_520, ge=1_048_576, le=52_428_800)
    scanner_respect_robots_txt: bool = True
    scanner_enable_playwright: bool = False
    scanner_stale_timeout_minutes: int = Field(default=30, ge=5, le=360)
    scanner_max_retries: int = Field(default=2, ge=0, le=5)
    scanner_trusted_internal_hosts: str = ""

    content_max_context_chars: int = Field(default=4000, ge=500, le=20000)
    content_max_keywords: int = Field(default=12, ge=3, le=30)
    content_near_duplicate_threshold: float = Field(default=88.0, ge=50.0, le=100.0)

    media_storage_mode: str = "url_only"
    media_max_file_bytes: int = Field(default=5_242_880, ge=65_536, le=20_971_520)
    media_max_dimension_px: int = Field(default=4096, ge=256, le=16384)
    media_download_timeout_seconds: float = Field(default=15.0, ge=2.0, le=60.0)

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Invalid IANA timezone: {value}") from exc
        return value

    @field_validator("session_cookie_samesite")
    @classmethod
    def validate_samesite(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("SESSION_COOKIE_SAMESITE must be 'lax', 'strict', or 'none'")
        return normalized

    @field_validator("media_storage_mode")
    @classmethod
    def validate_media_storage_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"url_only", "local"}:
            raise ValueError("MEDIA_STORAGE_MODE must be 'url_only' or 'local'")
        return normalized

    @property
    def trusted_internal_host_set(self) -> set[str]:
        return {
            host.strip().lower()
            for host in self.scanner_trusted_internal_hosts.split(",")
            if host.strip()
        }

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def resolved_storage_root(self) -> Path:
        raw = Path(self.storage_root)
        if raw.is_absolute():
            return raw
        return (PROJECT_ROOT / raw).resolve()

    @property
    def is_root_db_user(self) -> bool:
        return self.db_user.strip().lower() == "root"

    @property
    def has_configured_db_password(self) -> bool:
        return bool(self.db_password) and not self.db_password.startswith("CHANGE_ME")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
