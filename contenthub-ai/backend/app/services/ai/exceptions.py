from __future__ import annotations

from app.core.exceptions import AppError


class AiError(AppError):
    """Base error for Phase 3 Gemini AI, prompt, knowledge, cache, and generation flows."""


class AiProviderNotConfiguredError(AiError):
    def __init__(self, detail: str = "No active Gemini AI configuration is available.") -> None:
        super().__init__(detail, status_code=400, code="AI_PROVIDER_NOT_CONFIGURED")


class AiQuotaExhaustedError(AiError):
    def __init__(
        self,
        detail: str = "Application AI quota has been exhausted; job deferred safely.",
        *,
        code: str = "AI_QUOTA_EXHAUSTED",
    ) -> None:
        super().__init__(detail, status_code=429, code=code)


class AiTransientError(AiError):
    def __init__(
        self,
        detail: str,
        *,
        code: str = "AI_TRANSIENT_ERROR",
        status_code: int = 503,
    ) -> None:
        super().__init__(detail, status_code=status_code, code=code)


class AiPermanentError(AiError):
    def __init__(
        self,
        detail: str,
        *,
        code: str = "AI_PERMANENT_ERROR",
        status_code: int = 400,
    ) -> None:
        super().__init__(detail, status_code=status_code, code=code)


class AiResponseValidationError(AiError):
    def __init__(self, detail: str, code: str = "AI_RESPONSE_VALIDATION_ERROR") -> None:
        super().__init__(detail, status_code=422, code=code)


class PromptSecurityError(AiError):
    def __init__(self, detail: str, code: str = "PROMPT_SECURITY_ERROR") -> None:
        super().__init__(detail, status_code=422, code=code)
