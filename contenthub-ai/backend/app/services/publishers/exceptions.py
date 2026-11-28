from __future__ import annotations

from app.core.logging import redact_text

ERROR_CATEGORY_HTTP_DEFAULTS: dict[str, str] = {
    "expired_credentials": "Access token or refresh token has expired; reconnect or refresh.",
    "invalid_credentials": "Provider rejected the stored credentials.",
    "missing_permissions": "Required platform permissions/scopes have not been granted.",
    "unsupported_account": "Account type is unsupported for official API publishing.",
    "rate_limited": "Platform API rate limit exceeded.",
    "network_error": "Transient network or TLS error communicating with provider.",
    "provider_outage": "Upstream provider returned a temporary 5xx outage.",
    "invalid_media": "Attached media failed format, dimension, aspect ratio, or size validation.",
    "rejected_content": "Platform rejected post content or length.",
    "policy_restriction": "Account or content is restricted by official platform policy.",
    "unknown_result": "Submission outcome is uncertain and requires verification before retry.",
}


class PublisherError(Exception):
    """Typed publishing error with redacted explanation and retry/verification metadata."""

    def __init__(
        self,
        message: str,
        *,
        error_category: str,
        code: str = "PUBLISHING_ERROR",
        http_status: int | None = None,
        retryable: bool = False,
        requires_verification: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        safe_msg = redact_text(message)[:500]
        super().__init__(safe_msg)
        self.message = safe_msg
        self.error_category = error_category
        self.code = code
        self.http_status = http_status
        self.retryable = retryable
        self.requires_verification = requires_verification
        self.retry_after_seconds = retry_after_seconds


class VerificationRequiredError(PublisherError):
    """Raised when an external publish request timed out or failed ambiguously post-send."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "VERIFICATION_REQUIRED",
        http_status: int | None = None,
    ) -> None:
        super().__init__(
            message,
            error_category="unknown_result",
            code=code,
            http_status=http_status,
            retryable=False,
            requires_verification=True,
        )
