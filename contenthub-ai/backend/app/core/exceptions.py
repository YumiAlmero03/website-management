from __future__ import annotations


class AppError(Exception):
    """Base application error translated into structured JSON API responses."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int = 400,
        code: str = "APP_ERROR",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code
        self.headers = headers or {}


class AuthenticationError(AppError):
    def __init__(
        self, detail: str = "Authentication required.", code: str = "UNAUTHORIZED"
    ) -> None:
        super().__init__(detail, status_code=401, code=code)


class AuthorizationError(AppError):
    def __init__(self, detail: str = "Forbidden.", code: str = "FORBIDDEN") -> None:
        super().__init__(detail, status_code=403, code=code)


class RateLimitError(AppError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            "Too many login attempts. Please wait before trying again.",
            status_code=429,
            code="RATE_LIMITED",
            headers={"Retry-After": str(max(1, retry_after_seconds))},
        )


class ValidationAppError(AppError):
    def __init__(self, detail: str, code: str = "VALIDATION_ERROR") -> None:
        super().__init__(detail, status_code=422, code=code)


class ConflictError(AppError):
    def __init__(self, detail: str, code: str = "CONFLICT") -> None:
        super().__init__(detail, status_code=409, code=code)


class NotFoundError(AppError):
    def __init__(self, detail: str = "Resource not found.", code: str = "NOT_FOUND") -> None:
        super().__init__(detail, status_code=404, code=code)


class ConfigurationError(AppError):
    def __init__(self, detail: str, code: str = "CONFIGURATION_ERROR") -> None:
        super().__init__(detail, status_code=500, code=code)


class ServiceUnavailableError(AppError):
    def __init__(
        self,
        detail: str = "Database or required backing service is unavailable.",
        code: str = "SERVICE_UNAVAILABLE",
    ) -> None:
        super().__init__(detail, status_code=503, code=code)
