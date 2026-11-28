from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.ai_provider import AiProvider
from app.models.base import utc_now
from app.repositories.ai_repo import AiRepositoryProtocol
from app.services.ai.exceptions import AiQuotaExhaustedError


@dataclass(frozen=True)
class QuotaSnapshot:
    status: str  # ok | daily_requests_exhausted | daily_tokens_exhausted | rpm_exhausted | disabled
    requests_today: int
    requests_last_minute: int
    measured_tokens_today: int
    daily_request_limit: int
    daily_token_limit: int
    per_minute_request_limit: int
    requests_remaining: int
    tokens_remaining: int
    reason: str | None = None


def utc_day_window_start(timezone_name: str) -> datetime:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = UTC
    local_midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC).replace(tzinfo=None)


class QuotaManager:
    """Enforces free-first application request and token quotas.

    Never performs silent paid fallback or automatic API key rotation.
    """

    def __init__(
        self, *, ai_repo: AiRepositoryProtocol, timezone_name: str = "Asia/Manila"
    ) -> None:
        self.ai_repo = ai_repo
        self.timezone_name = timezone_name

    def evaluate(
        self,
        provider: AiProvider,
        *,
        planned_input_tokens: int = 0,
    ) -> QuotaSnapshot:
        day_start = utc_day_window_start(self.timezone_name)
        now = utc_now().replace(tzinfo=None)
        minute_cutoff = now - timedelta(seconds=60)

        logs = self.ai_repo.list_logs_since(day_start)
        provider_api_logs = [
            log
            for log in logs
            if log.ai_provider_id == provider.id
            and not log.cache_hit
            and log.status in {"succeeded", "failed", "rate_limited", "timeout", "invalid_response"}
        ]
        requests_today = len(provider_api_logs)
        requests_last_minute = sum(
            1 for log in provider_api_logs if log.created_at >= minute_cutoff
        )

        # Prefer measured tokens; fall back to estimated when measured is absent for quota guard
        tokens_today = 0
        for log in provider_api_logs:
            if log.total_measured_tokens is not None:
                tokens_today += log.total_measured_tokens
            elif log.estimated_input_tokens is not None:
                tokens_today += log.estimated_input_tokens

        req_rem = max(0, provider.daily_request_limit - requests_today)
        tok_rem = max(0, provider.daily_token_limit - tokens_today)

        if not provider.generation_enabled or not provider.is_active:
            return QuotaSnapshot(
                status="disabled",
                requests_today=requests_today,
                requests_last_minute=requests_last_minute,
                measured_tokens_today=tokens_today,
                daily_request_limit=provider.daily_request_limit,
                daily_token_limit=provider.daily_token_limit,
                per_minute_request_limit=provider.per_minute_request_limit,
                requests_remaining=req_rem,
                tokens_remaining=tok_rem,
                reason="AI generation is disabled for this Gemini provider configuration.",
            )

        if requests_today >= provider.daily_request_limit:
            return QuotaSnapshot(
                status="daily_requests_exhausted",
                requests_today=requests_today,
                requests_last_minute=requests_last_minute,
                measured_tokens_today=tokens_today,
                daily_request_limit=provider.daily_request_limit,
                daily_token_limit=provider.daily_token_limit,
                per_minute_request_limit=provider.per_minute_request_limit,
                requests_remaining=0,
                tokens_remaining=tok_rem,
                reason=(
                    f"Daily application request limit reached "
                    f"({requests_today}/{provider.daily_request_limit})."
                ),
            )

        if tokens_today + planned_input_tokens > provider.daily_token_limit:
            return QuotaSnapshot(
                status="daily_tokens_exhausted",
                requests_today=requests_today,
                requests_last_minute=requests_last_minute,
                measured_tokens_today=tokens_today,
                daily_request_limit=provider.daily_request_limit,
                daily_token_limit=provider.daily_token_limit,
                per_minute_request_limit=provider.per_minute_request_limit,
                requests_remaining=req_rem,
                tokens_remaining=0,
                reason=(
                    f"Daily application token limit reached "
                    f"({tokens_today}/{provider.daily_token_limit})."
                ),
            )

        if requests_last_minute >= provider.per_minute_request_limit:
            return QuotaSnapshot(
                status="rpm_exhausted",
                requests_today=requests_today,
                requests_last_minute=requests_last_minute,
                measured_tokens_today=tokens_today,
                daily_request_limit=provider.daily_request_limit,
                daily_token_limit=provider.daily_token_limit,
                per_minute_request_limit=provider.per_minute_request_limit,
                requests_remaining=req_rem,
                tokens_remaining=tok_rem,
                reason=(
                    f"Per-minute rate limit reached "
                    f"({requests_last_minute}/{provider.per_minute_request_limit} RPM)."
                ),
            )

        return QuotaSnapshot(
            status="ok",
            requests_today=requests_today,
            requests_last_minute=requests_last_minute,
            measured_tokens_today=tokens_today,
            daily_request_limit=provider.daily_request_limit,
            daily_token_limit=provider.daily_token_limit,
            per_minute_request_limit=provider.per_minute_request_limit,
            requests_remaining=req_rem,
            tokens_remaining=tok_rem,
            reason=None,
        )

    def ensure_available(
        self, provider: AiProvider, *, planned_input_tokens: int = 0
    ) -> QuotaSnapshot:
        snap = self.evaluate(provider, planned_input_tokens=planned_input_tokens)
        if snap.status != "ok":
            raise AiQuotaExhaustedError(
                snap.reason or "AI quota unavailable.",
                code=f"QUOTA_{snap.status.upper()}",
            )
        return snap
