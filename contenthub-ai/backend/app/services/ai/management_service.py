from __future__ import annotations

import csv
import io
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import redact_text
from app.core.security import decrypt_secret, encrypt_secret, mask_secret_hint
from app.models.ai_generation_log import AiGenerationLog
from app.models.ai_provider import AiProvider
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.ai_repo import AiRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.ai import (
    AiGenerationLogListResponse,
    AiGenerationLogResponse,
    AiProviderCreateRequest,
    AiProviderModelInfo,
    AiProviderModelsResponse,
    AiProviderResponse,
    AiProviderTestResponse,
    AiProviderUpdateRequest,
    AiUsageBreakdownItem,
    AiUsageSummaryResponse,
    CacheEntryResponse,
    CacheInvalidateRequest,
    CacheStatsResponse,
)
from app.schemas.common import PaginationMeta
from app.services.ai.exceptions import AiProviderNotConfiguredError
from app.services.ai.model_registry import normalize_model_name, sort_models_free_first
from app.services.ai.provider import AiProviderClientProtocol, ProviderModelDescriptor
from app.services.ai.localai import LocalAiProvider
from app.services.ai.quota_manager import QuotaManager, utc_day_window_start


class AiManagementService:
    """Manages Gemini configurations, connectivity tests, usage/quotas, history, and cache."""

    def __init__(
        self,
        *,
        settings: Settings,
        ai_repo: AiRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        provider_client: AiProviderClientProtocol,
    ) -> None:
        self.settings = settings
        self.ai_repo = ai_repo
        self.website_repo = website_repo
        self.activity_repo = activity_repo
        self.provider_client = provider_client
        self.quota_manager = QuotaManager(
            ai_repo=ai_repo, timezone_name=settings.app_timezone
        )

    @staticmethod
    def _model_to_schema(item: dict[str, Any] | ProviderModelDescriptor) -> AiProviderModelInfo:
        if isinstance(item, ProviderModelDescriptor):
            return AiProviderModelInfo(
                name=item.name,
                display_name=item.display_name,
                description=item.description,
                input_token_limit=item.input_token_limit,
                output_token_limit=item.output_token_limit,
                supported_actions=list(item.supported_actions),
                is_flash_recommended=item.is_flash_recommended,
            )
        return AiProviderModelInfo(**item)

    def _decrypt_provider_key(self, provider: AiProvider) -> str:
        if provider.encrypted_api_key:
            return decrypt_secret(provider.encrypted_api_key, self.settings.app_encryption_key)
        if provider.provider_type == "localai":
            return ""
        if self.settings.gemini_api_key and self.settings.gemini_api_key.strip():
            return self.settings.gemini_api_key.strip()
        raise AiProviderNotConfiguredError(
            f"Gemini configuration '{provider.name}' does not have an API key stored."
        )

    def _to_provider_response(self, row: AiProvider) -> AiProviderResponse:
        now = utc_now()
        masked: str | None = None
        has_key = bool(row.encrypted_api_key)
        if row.encrypted_api_key:
            try:
                plain = decrypt_secret(row.encrypted_api_key, self.settings.app_encryption_key)
                masked = mask_secret_hint(plain) or "••••••••"
            except Exception:
                masked = "••••••••"
        elif self.settings.gemini_api_key and self.settings.gemini_api_key.strip():
            has_key = True
            masked = mask_secret_hint(self.settings.gemini_api_key) or "env:GEMINI_API_KEY"

        models = [self._model_to_schema(m) for m in (row.available_models_json or [])]
        return AiProviderResponse(
            id=row.id,
            name=row.name,
            provider_type=row.provider_type,
            base_url=row.base_url,
            has_api_key=has_key,
            masked_api_key=masked,
            selected_model=row.selected_model,
            available_models=models,
            default_temperature=row.default_temperature,
            max_output_tokens=row.max_output_tokens,
            request_timeout_seconds=row.request_timeout_seconds,
            max_retry_attempts=row.max_retry_attempts,
            daily_request_limit=row.daily_request_limit,
            daily_token_limit=row.daily_token_limit,
            per_minute_request_limit=row.per_minute_request_limit,
            generation_enabled=row.generation_enabled,
            response_caching_enabled=row.response_caching_enabled,
            token_optimization_enabled=row.token_optimization_enabled,
            allow_paid_fallback=False if not row.allow_paid_fallback else row.allow_paid_fallback,
            is_default=row.is_default,
            is_active=row.is_active,
            last_test_status=row.last_test_status,
            last_test_latency_ms=row.last_test_latency_ms,
            last_test_error=row.last_test_error,
            last_verified_at=ensure_utc(row.last_verified_at),
            created_at=ensure_utc(row.created_at) or now,
            updated_at=ensure_utc(row.updated_at) or now,
        )

    def resolve_provider(self, provider_id: int | None = None) -> AiProvider:
        if provider_id is not None:
            found = self.ai_repo.get_provider_by_id(provider_id)
            if found is None:
                raise NotFoundError(f"Gemini provider configuration #{provider_id} not found.")
            return found
        default_provider = self.ai_repo.get_default_provider()
        if default_provider is None:
            raise AiProviderNotConfiguredError(
                "No active Gemini configuration found. Configure Gemini under AI Management first."
            )
        return default_provider

    def list_providers(self) -> list[AiProviderResponse]:
        return [self._to_provider_response(r) for r in self.ai_repo.list_providers()]

    def create_provider(
        self,
        payload: AiProviderCreateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> AiProviderResponse:
        name = payload.name.strip()
        if self.ai_repo.get_provider_by_name(name) is not None:
            raise ConflictError(f"AI configuration '{name}' already exists.")
        if payload.allow_paid_fallback:
            raise ValidationAppError(
                "Silent fallback to paid models is prohibited in Free-First mode."
            )

        encrypted_key = (
            encrypt_secret(payload.api_key.strip(), self.settings.app_encryption_key)
            if payload.api_key and payload.api_key.strip()
            else None
        )
        existing = self.ai_repo.list_providers()
        is_default = payload.is_default or len(existing) == 0
        if is_default:
            self.ai_repo.clear_default_providers()

        created = self.ai_repo.create_provider(
            {
                "name": name,
                "provider_type": payload.provider_type,
                "base_url": payload.base_url,
                "encrypted_api_key": encrypted_key,
                "selected_model": normalize_model_name(payload.selected_model),
                "available_models_json": [],
                "default_temperature": payload.default_temperature,
                "max_output_tokens": payload.max_output_tokens,
                "request_timeout_seconds": payload.request_timeout_seconds,
                "max_retry_attempts": payload.max_retry_attempts,
                "daily_request_limit": payload.daily_request_limit,
                "daily_token_limit": payload.daily_token_limit,
                "per_minute_request_limit": payload.per_minute_request_limit,
                "generation_enabled": payload.generation_enabled,
                "response_caching_enabled": payload.response_caching_enabled,
                "token_optimization_enabled": payload.token_optimization_enabled,
                "allow_paid_fallback": False,
                "is_default": is_default,
                "is_active": payload.is_active,
                "last_test_status": "untested",
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="ai_provider.created",
            level="info",
            message=f"Created Gemini configuration '{created.name}' ({created.selected_model}).",
            metadata={"provider_id": created.id, "model": created.selected_model},
            ip_address=ip_address,
        )
        return self._to_provider_response(created)

    def update_provider(
        self,
        provider_id: int,
        payload: AiProviderUpdateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> AiProviderResponse:
        existing = self.ai_repo.get_provider_by_id(provider_id)
        if existing is None:
            raise NotFoundError(f"Gemini configuration #{provider_id} not found.")
        if payload.allow_paid_fallback:
            raise ValidationAppError(
                "Silent fallback to paid models is prohibited in Free-First mode."
            )

        updates: dict[str, Any] = {}
        if payload.name is not None:
            clean_name = payload.name.strip()
            other = self.ai_repo.get_provider_by_name(clean_name)
            if other is not None and other.id != provider_id:
                raise ConflictError(f"Gemini configuration '{clean_name}' already exists.")
            updates["name"] = clean_name
        if payload.provider_type is not None:
            updates["provider_type"] = payload.provider_type
        if payload.base_url is not None:
            updates["base_url"] = payload.base_url.strip().rstrip("/") or None
        if payload.clear_api_key:
            updates["encrypted_api_key"] = None
            updates["last_test_status"] = "untested"
        elif payload.api_key is not None and payload.api_key.strip():
            updates["encrypted_api_key"] = encrypt_secret(
                payload.api_key.strip(), self.settings.app_encryption_key
            )
            updates["last_test_status"] = "untested"

        for field in (
            "default_temperature",
            "max_output_tokens",
            "request_timeout_seconds",
            "max_retry_attempts",
            "daily_request_limit",
            "daily_token_limit",
            "per_minute_request_limit",
            "generation_enabled",
            "response_caching_enabled",
            "token_optimization_enabled",
            "is_active",
        ):
            val = getattr(payload, field)
            if val is not None:
                updates[field] = val

        if payload.selected_model is not None:
            updates["selected_model"] = normalize_model_name(payload.selected_model)
        updates["allow_paid_fallback"] = False

        if payload.is_default is True:
            self.ai_repo.clear_default_providers(except_id=provider_id)
            updates["is_default"] = True
        elif payload.is_default is False:
            updates["is_default"] = False

        updated = self.ai_repo.update_provider(provider_id, updates)
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="ai_provider.updated",
            level="info",
            message=f"Updated AI configuration '{updated.name}' ({updated.provider_type}).",
            metadata={"provider_id": updated.id, "updated_fields": sorted(updates.keys())},
            ip_address=ip_address,
        )
        return self._to_provider_response(updated)

    def test_provider(
        self,
        provider_id: int,
        *,
        verify_generation: bool = False,
        user_id: int | None = None,
        ip_address: str | None = None,
    ) -> AiProviderTestResponse:
        provider = self.ai_repo.get_provider_by_id(provider_id)
        if provider is None:
            raise NotFoundError(f"Gemini configuration #{provider_id} not found.")

        try:
            api_key = self._decrypt_provider_key(provider)
        except AiProviderNotConfiguredError as exc:
            self.ai_repo.update_provider(
                provider.id,
                {"last_test_status": "error", "last_test_error": str(exc)[:500]},
            )
            return AiProviderTestResponse(
                connected=False,
                provider_id=provider.id,
                selected_model=provider.selected_model,
                model_available=False,
                error_detail=str(exc),
            )

        if provider.provider_type == "localai":
            res = LocalAiProvider().test_connection(
                base_url=provider.base_url or "http://127.0.0.1:8080/v1",
                api_key=api_key,
                selected_model=provider.selected_model,
                timeout_seconds=provider.request_timeout_seconds,
                verify_generation=verify_generation,
            )
        else:
            res = self.provider_client.test_connection(
                api_key=api_key,
                selected_model=provider.selected_model,
                timeout_seconds=provider.request_timeout_seconds,
                verify_generation=verify_generation,
            )
        now_naive = utc_now_naive()
        safe_err: str | None = None
        if res.error_detail:
            safe_err = redact_text(res.error_detail).replace(api_key, "[REDACTED]")
        serialized_models = [self._model_to_schema(m).model_dump() for m in res.discovered_models]
        updates: dict[str, Any] = {
            "last_test_status": "connected" if res.connected else "error",
            "last_test_latency_ms": res.latency_ms,
            "last_test_error": safe_err[:500] if safe_err else None,
        }
        if serialized_models:
            updates["available_models_json"] = serialized_models
        if res.connected:
            updates["last_verified_at"] = now_naive
        self.ai_repo.update_provider(provider.id, updates)

        if verify_generation and res.model_available:
            self.ai_repo.create_log(
                {
                    "job_id": None,
                    "ai_provider_id": provider.id,
                    "prompt_template_id": None,
                    "website_id": None,
                    "website_content_id": None,
                    "task_type": "connection_probe",
                    "model_name": res.selected_model,
                    "context_mode": "metadata_only",
                    "cache_hit": False,
                    "cache_key_hash": None,
                    "status": "succeeded" if res.connected else "failed",
                    "estimated_input_tokens": 5,
                    "measured_input_tokens": None,
                    "measured_output_tokens": None,
                    "total_measured_tokens": res.generation_probe_tokens,
                    "token_usage_status": (
                        "measured" if res.generation_probe_tokens is not None else "unknown"
                    ),
                    "estimated_cost_usd": None,
                    "latency_ms": res.latency_ms,
                    "error_code": None if res.connected else "PROBE_FAILED",
                    "error_message": safe_err[:500] if safe_err else None,
                }
            )

        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="ai_provider.tested",
            level="info" if res.connected else "warning",
            message=(
                f"Tested Gemini provider '{provider.name}': "
                f"{'connected' if res.connected else 'failed'}."
            ),
            metadata={
                "provider_id": provider.id,
                "connected": res.connected,
                "model_available": res.model_available,
                "latency_ms": res.latency_ms,
            },
            ip_address=ip_address,
        )

        return AiProviderTestResponse(
            connected=res.connected,
            provider_id=provider.id,
            selected_model=res.selected_model,
            model_available=res.model_available,
            latency_ms=res.latency_ms,
            discovered_model_count=len(res.discovered_models),
            error_detail=safe_err,
            last_verified_at=(
                ensure_utc(now_naive) if res.connected else ensure_utc(provider.last_verified_at)
            ),
            generation_probe_tokens=res.generation_probe_tokens,
        )

    def list_provider_models(
        self, provider_id: int, *, refresh: bool = True
    ) -> AiProviderModelsResponse:
        provider = self.ai_repo.get_provider_by_id(provider_id)
        if provider is None:
            raise NotFoundError(f"Gemini configuration #{provider_id} not found.")

        if refresh:
            api_key = self._decrypt_provider_key(provider)
            descriptors = sort_models_free_first(
                self.provider_client.list_models(
                    api_key=api_key, timeout_seconds=provider.request_timeout_seconds
                )
            )
            models = [self._model_to_schema(d) for d in descriptors]
            self.ai_repo.update_provider(
                provider.id, {"available_models_json": [m.model_dump() for m in models]}
            )
            return AiProviderModelsResponse(
                provider_id=provider.id,
                selected_model=provider.selected_model,
                models=models,
                fetched_live=True,
            )

        models = [self._model_to_schema(m) for m in (provider.available_models_json or [])]
        return AiProviderModelsResponse(
            provider_id=provider.id,
            selected_model=provider.selected_model,
            models=models,
            fetched_live=False,
        )

    # --------------------------------------------------------------------------
    # Logs, Usage, CSV Export & Cache Management
    # --------------------------------------------------------------------------
    def _to_log_response(self, row: AiGenerationLog) -> AiGenerationLogResponse:
        provider = self.ai_repo.get_provider_by_id(row.ai_provider_id)
        site = self.website_repo.get_by_id(row.website_id) if row.website_id else None
        return AiGenerationLogResponse(
            id=row.id,
            job_id=row.job_id,
            ai_provider_id=row.ai_provider_id,
            provider_name=provider.name if provider else None,
            prompt_template_id=row.prompt_template_id,
            website_id=row.website_id,
            website_name=site.name if site else None,
            website_content_id=row.website_content_id,
            task_type=row.task_type,
            model_name=row.model_name,
            context_mode=row.context_mode,
            cache_hit=row.cache_hit,
            cache_key_hash=row.cache_key_hash,
            status=row.status,
            estimated_input_tokens=row.estimated_input_tokens,
            measured_input_tokens=row.measured_input_tokens,
            measured_output_tokens=row.measured_output_tokens,
            total_measured_tokens=row.total_measured_tokens,
            token_usage_status=row.token_usage_status,
            estimated_cost_usd=(
                float(row.estimated_cost_usd) if row.estimated_cost_usd is not None else None
            ),
            latency_ms=row.latency_ms,
            truncated_input=row.truncated_input,
            truncation_note=row.truncation_note,
            error_code=row.error_code,
            error_message=row.error_message,
            created_at=ensure_utc(row.created_at) or utc_now(),
        )

    def list_history(
        self,
        *,
        website_id: int | None = None,
        provider_id: int | None = None,
        task_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> AiGenerationLogListResponse:
        rows, total = self.ai_repo.list_logs(
            website_id=website_id,
            provider_id=provider_id,
            task_type=task_type,
            status=status,
            page=page,
            page_size=page_size,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return AiGenerationLogListResponse(
            items=[self._to_log_response(r) for r in rows],
            meta=PaginationMeta(
                page=page, page_size=page_size, total_items=total, total_pages=total_pages
            ),
        )

    def export_history_csv(
        self,
        *,
        website_id: int | None = None,
        provider_id: int | None = None,
        task_type: str | None = None,
        status: str | None = None,
    ) -> str:
        rows, _ = self.ai_repo.list_logs(
            website_id=website_id,
            provider_id=provider_id,
            task_type=task_type,
            status=status,
            page=1,
            page_size=5000,
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "created_at_utc",
                "provider",
                "website",
                "task_type",
                "model_name",
                "context_mode",
                "cache_hit",
                "status",
                "estimated_input_tokens",
                "measured_input_tokens",
                "measured_output_tokens",
                "total_measured_tokens",
                "token_usage_status",
                "latency_ms",
                "error_code",
                "error_message",
            ]
        )
        for row in rows:
            item = self._to_log_response(row)
            writer.writerow(
                [
                    item.id,
                    item.created_at.isoformat(),
                    item.provider_name or item.ai_provider_id,
                    item.website_name or "",
                    item.task_type,
                    item.model_name,
                    item.context_mode,
                    item.cache_hit,
                    item.status,
                    item.estimated_input_tokens if item.estimated_input_tokens is not None else "",
                    item.measured_input_tokens if item.measured_input_tokens is not None else "",
                    item.measured_output_tokens if item.measured_output_tokens is not None else "",
                    item.total_measured_tokens if item.total_measured_tokens is not None else "",
                    item.token_usage_status,
                    item.latency_ms if item.latency_ms is not None else "",
                    item.error_code or "",
                    item.error_message or "",
                ]
            )
        return buf.getvalue()

    def get_usage_summary(self) -> AiUsageSummaryResponse:
        day_start = utc_day_window_start(self.settings.app_timezone)
        try:
            tz = ZoneInfo(self.settings.app_timezone)
        except Exception:
            tz = UTC
        local_month_start = datetime.now(tz).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        month_start = local_month_start.astimezone(UTC).replace(tzinfo=None)
        since = min(day_start, month_start)
        logs = self.ai_repo.list_logs_since(since)

        today_logs = [log for log in logs if log.created_at >= day_start]
        month_logs = [log for log in logs if log.created_at >= month_start]

        api_today = [log for log in today_logs if not log.cache_hit]
        api_month = [log for log in month_logs if not log.cache_hit]
        cache_hits_today = sum(1 for log in today_logs if log.cache_hit)

        measured_in = [
            log.measured_input_tokens for log in api_today if log.measured_input_tokens is not None
        ]
        measured_out = [
            log.measured_output_tokens
            for log in api_today
            if log.measured_output_tokens is not None
        ]
        measured_tot_today = [
            log.total_measured_tokens for log in api_today if log.total_measured_tokens is not None
        ]
        measured_tot_month = [
            log.total_measured_tokens for log in api_month if log.total_measured_tokens is not None
        ]
        latencies = [log.latency_ms for log in api_today if log.latency_ms is not None]

        total_requests_today_all = len(today_logs)
        hit_rate = (
            round((cache_hits_today / total_requests_today_all) * 100.0, 2)
            if total_requests_today_all > 0
            else 0.0
        )

        # Breakdowns across this month's logs
        by_site: dict[str, AiUsageBreakdownItem] = {}
        by_model: dict[str, AiUsageBreakdownItem] = {}
        by_task: dict[str, AiUsageBreakdownItem] = {}
        for log in month_logs:
            tok = log.total_measured_tokens or 0
            # Website breakdown
            skey = str(log.website_id or "global")
            if skey not in by_site:
                site_obj = self.website_repo.get_by_id(log.website_id) if log.website_id else None
                slabel = site_obj.name if site_obj else "Global / Diagnostics"
                by_site[skey] = AiUsageBreakdownItem(key=skey, label=slabel)
            if log.cache_hit:
                by_site[skey].cache_hits += 1
            else:
                by_site[skey].requests += 1
                by_site[skey].measured_tokens += tok

            # Model breakdown
            mkey = log.model_name
            if mkey not in by_model:
                by_model[mkey] = AiUsageBreakdownItem(key=mkey, label=mkey)
            if log.cache_hit:
                by_model[mkey].cache_hits += 1
            else:
                by_model[mkey].requests += 1
                by_model[mkey].measured_tokens += tok

            # Task type breakdown
            tkey = log.task_type
            if tkey not in by_task:
                by_task[tkey] = AiUsageBreakdownItem(key=tkey, label=tkey.replace("_", " ").title())
            if log.cache_hit:
                by_task[tkey].cache_hits += 1
            else:
                by_task[tkey].requests += 1
                by_task[tkey].measured_tokens += tok

        default_provider = self.ai_repo.get_default_provider()
        quota_status = "unconfigured"
        req_limit = None
        req_rem = None
        tok_limit = None
        tok_rem = None
        if default_provider is not None:
            qsnap = self.quota_manager.evaluate(default_provider)
            quota_status = qsnap.status
            req_limit = qsnap.daily_request_limit
            req_rem = qsnap.requests_remaining
            tok_limit = qsnap.daily_token_limit
            tok_rem = qsnap.tokens_remaining

        return AiUsageSummaryResponse(
            requests_today=len(api_today),
            requests_this_month=len(api_month),
            estimated_input_tokens_today=sum(log.estimated_input_tokens or 0 for log in api_today),
            measured_input_tokens_today=sum(measured_in) if measured_in else None,
            measured_output_tokens_today=sum(measured_out) if measured_out else None,
            total_measured_tokens_today=sum(measured_tot_today) if measured_tot_today else None,
            total_measured_tokens_month=sum(measured_tot_month) if measured_tot_month else None,
            cache_hits_today=cache_hits_today,
            cache_hit_rate_percent=hit_rate,
            failed_requests_today=sum(
                1
                for log in today_logs
                if log.status in {"failed", "rate_limited", "timeout", "invalid_response"}
            ),
            deferred_jobs_count=self.ai_repo.count_jobs_by_status("deferred"),
            queued_jobs_count=self.ai_repo.count_jobs_by_status("queued"),
            average_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else None,
            active_provider_name=default_provider.name if default_provider else None,
            active_model=default_provider.selected_model if default_provider else None,
            daily_request_limit=req_limit,
            daily_requests_remaining=req_rem,
            daily_token_limit=tok_limit,
            daily_tokens_remaining=tok_rem,
            quota_status=quota_status,
            estimated_cost_usd_month=None,
            usage_by_website=list(by_site.values()),
            usage_by_model=list(by_model.values()),
            usage_by_task_type=list(by_task.values()),
        )

    def get_cache_stats(self, *, website_id: int | None = None) -> CacheStatsResponse:
        stats = self.ai_repo.get_cache_stats()
        entries = self.ai_repo.list_cache_entries(website_id=website_id, limit=100)
        usage = self.get_usage_summary()
        return CacheStatsResponse(
            total_entries=stats["total_entries"],
            active_entries=stats["active_entries"],
            expired_entries=stats["expired_entries"],
            total_hits=stats["total_hits"],
            cache_hit_rate_percent=usage.cache_hit_rate_percent,
            entries=[
                CacheEntryResponse(
                    id=e.id,
                    cache_key_hash=e.cache_key_hash,
                    ai_provider_id=e.ai_provider_id,
                    website_id=e.website_id,
                    website_name=(
                        s.name
                        if (s := self.website_repo.get_by_id(e.website_id)) is not None
                        else None
                    ),
                    website_content_id=e.website_content_id,
                    task_type=e.task_type,
                    model_name=e.model_name,
                    prompt_version=e.prompt_version,
                    context_mode=e.context_mode,
                    language=e.language,
                    input_tokens=e.input_tokens,
                    output_tokens=e.output_tokens,
                    hit_count=e.hit_count,
                    last_hit_at=ensure_utc(e.last_hit_at),
                    expires_at=ensure_utc(e.expires_at) or (utc_now() + timedelta(days=1)),
                    created_at=ensure_utc(e.created_at) or utc_now(),
                )
                for e in entries
            ],
        )

    def invalidate_cache(
        self,
        payload: CacheInvalidateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> int:
        removed = self.ai_repo.delete_cache_entries(
            cache_ids=payload.cache_ids,
            website_id=payload.website_id,
            expired_only=payload.expired_only,
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="ai_cache.invalidated",
            level="info",
            message=f"Cleared {removed} AI response cache entr{'y' if removed == 1 else 'ies'}.",
            metadata={"removed": removed, "website_id": payload.website_id},
            ip_address=ip_address,
        )
        return removed
