from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import Settings
from app.core.exceptions import ValidationAppError
from app.core.security import encrypt_secret
from app.models.base import ensure_utc
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.settings_repo import SettingsRepositoryProtocol
from app.schemas.settings import SettingItemResponse, SettingsListResponse, SettingUpdateItem


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    category: str
    label: str
    description: str
    value_type: str  # "string" | "integer" | "number" | "boolean" | "enum" | "timezone" | "secret"
    default_value: Any
    is_secret: bool = False
    allowed_values: tuple[str, ...] = ()
    min_value: float | None = None
    max_value: float | None = None


def build_setting_catalog(settings: Settings) -> list[SettingDefinition]:
    return [
        SettingDefinition(
            key="app.timezone",
            category="general",
            label="Display Timezone",
            description=(
                "IANA timezone used to render schedules and logs (timestamps are stored in UTC)."
            ),
            value_type="timezone",
            default_value=settings.app_timezone,
        ),
        SettingDefinition(
            key="app.instance_label",
            category="general",
            label="Instance Label",
            description="Private workspace label shown in the administration header.",
            value_type="string",
            default_value=settings.app_name,
        ),
        SettingDefinition(
            key="publishing.default_mode",
            category="publishing",
            label="Default Publishing Mode",
            description=(
                "Semi-automatic (human approval before publishing) is recommended as the default."
            ),
            value_type="enum",
            default_value="semi_automatic",
            allowed_values=("manual", "semi_automatic", "automatic"),
        ),
        SettingDefinition(
            key="publishing.require_approval",
            category="publishing",
            label="Require Approval Before External Publishing",
            description=(
                "Prevent external publishing unless explicitly approved "
                "or matched by an automation rule."
            ),
            value_type="boolean",
            default_value=True,
        ),
        SettingDefinition(
            key="resources.cpu_warning_percent",
            category="resource_guardian",
            label="CPU Warning Threshold (%)",
            description=(
                "Delay nonessential crawling and optional AI research "
                "when CPU exceeds this percentage."
            ),
            value_type="number",
            default_value=settings.resource_cpu_warning_percent,
            min_value=10,
            max_value=95,
        ),
        SettingDefinition(
            key="resources.cpu_critical_percent",
            category="resource_guardian",
            label="CPU Critical Threshold (%)",
            description="Pause expensive background jobs when CPU reaches this critical threshold.",
            value_type="number",
            default_value=settings.resource_cpu_critical_percent,
            min_value=20,
            max_value=100,
        ),
        SettingDefinition(
            key="resources.ram_warning_percent",
            category="resource_guardian",
            label="RAM Warning Threshold (%)",
            description=(
                "Protect co-hosted production websites when system memory exceeds this threshold."
            ),
            value_type="number",
            default_value=settings.resource_ram_warning_percent,
            min_value=20,
            max_value=95,
        ),
        SettingDefinition(
            key="resources.load_avg_threshold",
            category="resource_guardian",
            label="Load Average Threshold (1m)",
            description=(
                "Maximum 1-minute system load average before Resource Guardian defers heavy work."
            ),
            value_type="number",
            default_value=settings.resource_load_avg_threshold,
            min_value=1,
            max_value=128,
        ),
        SettingDefinition(
            key="resources.max_concurrent_generation",
            category="resource_guardian",
            label="Max Concurrent AI Generation Jobs",
            description=(
                "Maximum concurrent Gemini generation jobs allowed by the background worker."
            ),
            value_type="integer",
            default_value=settings.resource_max_concurrent_generation,
            min_value=1,
            max_value=10,
        ),
        SettingDefinition(
            key="resources.max_concurrent_browsers",
            category="resource_guardian",
            label="Max Concurrent Browser Fallbacks",
            description="Maximum concurrent Playwright fallback instances allowed simultaneously.",
            value_type="integer",
            default_value=settings.resource_max_concurrent_browsers,
            min_value=1,
            max_value=4,
        ),
        SettingDefinition(
            key="resources.recheck_interval_minutes",
            category="resource_guardian",
            label="Resource Recheck Interval (minutes)",
            description="Minutes between Resource Guardian checks before resuming deferred jobs.",
            value_type="integer",
            default_value=settings.resource_recheck_interval_minutes,
            min_value=1,
            max_value=60,
        ),
        SettingDefinition(
            key="seo.title_min_chars",
            category="seo",
            label="SEO Title Min Length",
            description="Advisory lower bound for SEO title checks (warning only).",
            value_type="integer",
            default_value=50,
            min_value=20,
            max_value=100,
        ),
        SettingDefinition(
            key="seo.title_max_chars",
            category="seo",
            label="SEO Title Max Length",
            description="Advisory upper bound for SEO title checks (warning only).",
            value_type="integer",
            default_value=60,
            min_value=30,
            max_value=120,
        ),
        SettingDefinition(
            key="seo.meta_description_min_chars",
            category="seo",
            label="Meta Description Min Length",
            description="Advisory lower bound for meta descriptions (warning only).",
            value_type="integer",
            default_value=130,
            min_value=50,
            max_value=200,
        ),
        SettingDefinition(
            key="seo.meta_description_max_chars",
            category="seo",
            label="Meta Description Max Length",
            description="Advisory upper bound for meta descriptions (warning only).",
            value_type="integer",
            default_value=160,
            min_value=80,
            max_value=320,
        ),
        SettingDefinition(
            key="backups.retention_days",
            category="backups",
            label="Database Backup Retention (days)",
            description="Number of days to retain automated daily MySQL backups.",
            value_type="integer",
            default_value=14,
            min_value=1,
            max_value=365,
        ),
        SettingDefinition(
            key="security.webhook_signing_secret",
            category="security",
            label="Internal Webhook Signing Secret",
            description=(
                "Optional secret encrypted at rest via Fernet (APP_ENCRYPTION_KEY). "
                "Leave empty to keep unchanged."
            ),
            value_type="secret",
            default_value=None,
            is_secret=True,
        ),
    ]


class SettingsService:
    def __init__(
        self,
        *,
        settings: Settings,
        settings_repo: SettingsRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
    ) -> None:
        self.settings = settings
        self.settings_repo = settings_repo
        self.activity_repo = activity_repo
        self._catalog = build_setting_catalog(settings)
        self._catalog_by_key = {item.key: item for item in self._catalog}

    def list_settings(self) -> SettingsListResponse:
        stored = {row.setting_key: row for row in self.settings_repo.list_all()}
        items: list[SettingItemResponse] = []
        categories: list[str] = []

        for definition in self._catalog:
            if definition.category not in categories:
                categories.append(definition.category)
            row = stored.get(definition.key)

            if definition.is_secret:
                has_value = bool(row and row.encrypted_value)
                value: Any = None
            elif row is not None:
                has_value = row.value_json is not None
                value = row.value_json
            else:
                has_value = definition.default_value is not None
                value = definition.default_value

            items.append(
                SettingItemResponse(
                    key=definition.key,
                    category=definition.category,
                    label=definition.label,
                    description=definition.description,
                    value_type=definition.value_type,
                    value=value,
                    is_secret=definition.is_secret,
                    has_value=has_value,
                    default_value=None if definition.is_secret else definition.default_value,
                    updated_at=ensure_utc(row.updated_at) if row else None,
                )
            )

        return SettingsListResponse(categories=categories, items=items)

    def get_effective_map(self) -> dict[str, Any]:
        """Return effective non-secret setting values with defaults applied."""
        stored = {row.setting_key: row for row in self.settings_repo.list_all()}
        effective: dict[str, Any] = {}
        for definition in self._catalog:
            if definition.is_secret:
                continue
            row = stored.get(definition.key)
            effective[definition.key] = (
                row.value_json
                if row is not None and row.value_json is not None
                else definition.default_value
            )
        return effective

    def _validate_value(self, definition: SettingDefinition, value: Any) -> Any:
        if definition.value_type == "boolean":
            if not isinstance(value, bool):
                raise ValidationAppError(f"Setting '{definition.key}' must be a boolean.")
            return value

        if definition.value_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationAppError(f"Setting '{definition.key}' must be an integer.")
            if definition.min_value is not None and value < definition.min_value:
                raise ValidationAppError(
                    f"Setting '{definition.key}' must be >= {int(definition.min_value)}."
                )
            if definition.max_value is not None and value > definition.max_value:
                raise ValidationAppError(
                    f"Setting '{definition.key}' must be <= {int(definition.max_value)}."
                )
            return value

        if definition.value_type == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValidationAppError(f"Setting '{definition.key}' must be a number.")
            numeric = float(value)
            if definition.min_value is not None and numeric < definition.min_value:
                raise ValidationAppError(
                    f"Setting '{definition.key}' must be >= {definition.min_value}."
                )
            if definition.max_value is not None and numeric > definition.max_value:
                raise ValidationAppError(
                    f"Setting '{definition.key}' must be <= {definition.max_value}."
                )
            return numeric

        if definition.value_type == "enum":
            if not isinstance(value, str) or value not in definition.allowed_values:
                allowed = ", ".join(definition.allowed_values)
                raise ValidationAppError(f"Setting '{definition.key}' must be one of: {allowed}.")
            return value

        if definition.value_type == "timezone":
            if not isinstance(value, str):
                raise ValidationAppError("Timezone must be a valid IANA timezone string.")
            try:
                ZoneInfo(value.strip())
            except ZoneInfoNotFoundError as exc:
                raise ValidationAppError(f"Unknown IANA timezone: {value}") from exc
            return value.strip()

        if definition.value_type == "secret":
            if value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                raise ValidationAppError(
                    f"Secret setting '{definition.key}' must be a non-empty string or null."
                )
            if len(value) > 4096:
                raise ValidationAppError(
                    f"Secret setting '{definition.key}' exceeds maximum length."
                )
            return value.strip()

        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
            raise ValidationAppError(
                f"Setting '{definition.key}' must be a non-empty string (max 200 chars)."
            )
        return value.strip()

    def bulk_update(
        self,
        *,
        updates: list[SettingUpdateItem],
        user_id: int,
        ip_address: str | None,
    ) -> SettingsListResponse:
        validated: list[tuple[SettingDefinition, Any]] = []
        for item in updates:
            definition = self._catalog_by_key.get(item.key)
            if definition is None:
                raise ValidationAppError(f"Unknown setting key: '{item.key}'.")
            cleaned = self._validate_value(definition, item.value)
            validated.append((definition, cleaned))

        # Cross-field consistency check for CPU warning vs critical thresholds.
        effective_preview = self.get_effective_map()
        for definition, cleaned in validated:
            if not definition.is_secret:
                effective_preview[definition.key] = cleaned

        if (
            effective_preview["resources.cpu_warning_percent"]
            >= effective_preview["resources.cpu_critical_percent"]
        ):
            raise ValidationAppError(
                "CPU warning threshold must be strictly lower than CPU critical threshold."
            )

        updated_keys: list[str] = []
        for definition, cleaned in validated:
            if definition.is_secret:
                if cleaned is None:
                    continue
                encrypted = encrypt_secret(cleaned, self.settings.app_encryption_key)
                self.settings_repo.upsert(
                    key=definition.key,
                    category=definition.category,
                    value_json=None,
                    encrypted_value=encrypted,
                    is_secret=True,
                    description=definition.description,
                    updated_by=user_id,
                )
            else:
                self.settings_repo.upsert(
                    key=definition.key,
                    category=definition.category,
                    value_json=cleaned,
                    encrypted_value=None,
                    is_secret=False,
                    description=definition.description,
                    updated_by=user_id,
                )
            updated_keys.append(definition.key)

        if updated_keys:
            self.activity_repo.create(
                user_id=user_id,
                actor_type="admin",
                category="settings",
                action="settings.updated",
                level="info",
                message=f"Updated {len(updated_keys)} application setting(s).",
                metadata={"updated_keys": updated_keys},
                ip_address=ip_address,
            )

        return self.list_settings()
