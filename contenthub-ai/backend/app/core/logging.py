from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "csrf",
    "fernet",
    "private_key",
    "credential",
    "encrypted_value",
)

_SENSITIVE_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(
            r"(?i)(password|passwd|secret|token|api_key|apikey|cookie|authorization)"
            r"(\s*[:=]\s*)([^\s,;'\"]+)"
        ),
        rf"\1\2{REDACTED}",
    ),
)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact_text(value: str) -> str:
    """Scrub inline credentials, bearer tokens, and secret assignments from log text."""
    sanitized = value
    for pattern, replacement in _SENSITIVE_TEXT_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def redact_value(value: Any) -> Any:
    """Recursively redact sensitive fields in dicts, lists, and strings."""
    if isinstance(value, dict):
        return {
            str(k): REDACTED if _is_sensitive_key(str(k)) else redact_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_mapping(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    redacted = redact_value(data)
    return redacted if isinstance(redacted, dict) else {"value": redacted}


class StructuredRedactingFormatter(logging.Formatter):
    """Structured JSON formatter that strips sensitive tokens from every log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        extra = getattr(record, "structured_extra", None)
        if isinstance(extra, dict):
            payload["context"] = redact_mapping(extra)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(*, debug: bool = False) -> None:
    root_logger = logging.getLogger("contenthub")
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredRedactingFormatter())
        root_logger.addHandler(handler)
    root_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"contenthub.{name}")
