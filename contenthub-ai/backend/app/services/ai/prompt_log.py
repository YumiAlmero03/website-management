from __future__ import annotations

import json
import re

from app.core.exceptions import ConfigurationError
from app.core.logging import REDACTED, get_logger, redact_text
from app.core.security import encrypt_secret

MAX_LOG_TEXT = 64_000
logger = get_logger("ai.prompt_log")

# JSON, quoted assignments, and URL query parameters can appear inside prompt text.
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:[\w-]*(?:password|passwd|secret|api[_-]?key|credential|private[_-]?key)"
    r"[\w-]*|(?:access|refresh|session|csrf|oauth)[_-]?token|(?:set[_-]?)?cookie|"
    r"authorization|x[_-]csrf[_-]token|token)\b[\"']?\s*[:=]\s*)"
    r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s&;,\"'<>}]+)"
)
_CREDENTIAL_HEADER = re.compile(r"(?im)^(\s*(?:set-cookie|cookie|authorization)\s*:\s*)[^\r\n]+")


def redact_ai_log_text(text: str, api_key: str = "") -> str:
    if api_key:
        text = text.replace(api_key, REDACTED)
    text = redact_text(text)
    text = _CREDENTIAL_HEADER.sub(lambda match: match[1] + REDACTED, text)
    def mask_assignment(match: re.Match[str]) -> str:
        quote = match[2][0] if match[2][0] in "\"'" else ""
        return f"{match[1]}{quote}{REDACTED}{quote}"

    return _CREDENTIAL_ASSIGNMENT.sub(mask_assignment, text)


def encrypt_prompt_exchange(
    encryption_key: str,
    *,
    system_instruction: str | None = None,
    user_prompt: str | None = None,
    response: str | None = None,
    api_key: str = "",
) -> str | None:
    values = {
        "system_instruction": system_instruction,
        "user_prompt": user_prompt,
        "response": response,
    }
    key = encryption_key.strip()
    sanitized = {
        field: redact_ai_log_text(value.replace(key, REDACTED) if key else value, api_key)
        for field, value in values.items() if value is not None
    }
    payload = {field: value[:MAX_LOG_TEXT] for field, value in sanitized.items()}
    try:
        return encrypt_secret(
            json.dumps({
                **payload,
                "truncated": any(len(value) > MAX_LOG_TEXT for value in sanitized.values()),
            }, ensure_ascii=False),
            encryption_key,
        )
    except ConfigurationError:
        logger.warning("Prompt text capture is unavailable because the encryption key is invalid.")
        return None
