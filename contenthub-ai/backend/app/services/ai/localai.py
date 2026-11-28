from __future__ import annotations

import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field, model_validator

from app.services.ai.exceptions import AiPermanentError, AiTransientError
from app.services.ai.provider import (
    ProviderGenerationResult,
    ProviderModelDescriptor,
    ProviderTestResult,
)


class LocalAiKeywordOutput(BaseModel):
    focus_keyphrase: str = Field(min_length=2, max_length=120)
    secondary_keywords: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "focus_keyphrase" not in normalized:
            for alt_key in ("primary_focus_keyphrase", "focus_keyword", "primary_keyphrase"):
                if normalized.get(alt_key):
                    normalized["focus_keyphrase"] = normalized[alt_key]
                    break
        if "secondary_keywords" not in normalized and isinstance(normalized.get("secondary"), list):
            normalized["secondary_keywords"] = normalized["secondary"]
        return normalized


class LocalAiKeywordResponseError(AiPermanentError):
    def __init__(self, result: ProviderGenerationResult) -> None:
        super().__init__(
            "LocalAI did not return valid keyword JSON.",
            code="LOCALAI_INVALID_RESPONSE",
            status_code=502,
        )
        self.result = result


def normalize_localai_base_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    if not value:
        return "http://127.0.0.1:8081"
    if value.endswith("/v1"):
        return value[:-3].rstrip("/")
    return value


def _extract_localai_json_text(message: dict[str, Any]) -> str:
    """Extract JSON payload from LocalAI `content`, falling back to `reasoning` channels."""
    raw_text = str(message.get("content") or "").strip()
    if not raw_text:
        raw_text = str(message.get("reasoning") or message.get("reasoning_content") or "").strip()
    if not raw_text:
        return ""
    cleaned = re.sub(r"(?is)<think>.*?</think>", "", raw_text).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


class LocalAiProvider:
    """OpenAI-compatible HTTPX client restricted to LocalAI keyword assistance."""

    def _request(self, base_url: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
        root = normalize_localai_base_url(base_url)
        url = f"{root}/v1{path}"
        timeout = kwargs.pop("timeout_seconds", 60)
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response

    def list_models(
        self, *, base_url: str, api_key: str = "", timeout_seconds: int = 45
    ) -> list[ProviderModelDescriptor]:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            response = self._request(
                base_url, "GET", "/models", headers=headers, timeout_seconds=timeout_seconds
            )
            payload = response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AiTransientError(
                "LocalAI is unavailable or the request timed out.",
                code="LOCALAI_UNAVAILABLE",
                status_code=503,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AiPermanentError(
                f"LocalAI model discovery failed with HTTP {exc.response.status_code}.",
                code="LOCALAI_HTTP_ERROR",
                status_code=exc.response.status_code,
            ) from exc

        models: list[ProviderModelDescriptor] = []
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("id") or "").strip()
            if name:
                models.append(
                    ProviderModelDescriptor(
                        name=name,
                        display_name=name,
                        description=item.get("object"),
                        is_flash_recommended=True,
                    )
                )
        return models

    def test_connection(
        self,
        *,
        base_url: str,
        api_key: str,
        selected_model: str,
        timeout_seconds: int = 45,
        verify_generation: bool = False,
    ) -> ProviderTestResult:
        started = time.monotonic()
        try:
            models = self.list_models(
                base_url=base_url, api_key=api_key, timeout_seconds=timeout_seconds
            )
        except Exception as exc:
            return ProviderTestResult(
                connected=False,
                selected_model=selected_model,
                model_available=False,
                latency_ms=int((time.monotonic() - started) * 1000),
                error_detail=str(exc)[:500],
            )
        names = {model.name for model in models}
        available = selected_model in names
        probe_err = None if available else "Selected model is not in the installed model list."
        return ProviderTestResult(
            connected=True,
            selected_model=selected_model,
            model_available=available,
            latency_ms=int((time.monotonic() - started) * 1000),
            discovered_models=models,
            error_detail=probe_err,
        )

    def select_keywords(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        system_instruction: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_output_tokens: int = 512,
        timeout_seconds: int = 60,
        max_retries: int = 1,
    ) -> tuple[LocalAiKeywordOutput, ProviderGenerationResult]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        last_error: Exception | None = None
        for _attempt in range(max_retries + 1):
            started = time.monotonic()
            try:
                response = self._request(
                    base_url,
                    "POST",
                    "/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout_seconds=timeout_seconds,
                )
                data = response.json()
                message = data["choices"][0]["message"]
                answer = _extract_localai_json_text({"content": message.get("content")})
                answer = re.sub(r"(?is)<think>.*$", "", answer).strip()
                usage = data.get("usage")
                usage = usage if isinstance(usage, dict) else {}
                input_tokens, output_tokens, total_tokens = (
                    value if type(value) is int and 0 <= value <= 2_147_483_647 else None
                    for value in (usage.get(key) for key in (
                        "prompt_tokens", "completion_tokens", "total_tokens"
                    ))
                )
                raw_model = data.get("model")
                used_model = raw_model.strip() if isinstance(raw_model, str) else ""
                try:
                    parsed = LocalAiKeywordOutput.model_validate_json(
                        _extract_localai_json_text(message)
                    )
                except ValueError:
                    parsed = None
                result = ProviderGenerationResult(
                    raw_text=answer or (parsed.model_dump_json() if parsed else ""),
                    model_name=(used_model or model_name)[:120],
                    latency_ms=int((time.monotonic() - started) * 1000),
                    measured_input_tokens=input_tokens,
                    measured_output_tokens=output_tokens,
                    total_measured_tokens=total_tokens,
                    raw_usage_available=any(
                        count is not None for count in (input_tokens, output_tokens, total_tokens)
                    ),
                )
                if parsed is None:
                    raise LocalAiKeywordResponseError(result)
                return parsed, result
            except httpx.TimeoutException as exc:
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                raise AiPermanentError(
                    f"LocalAI keyword request failed with HTTP {exc.response.status_code}.",
                    code="LOCALAI_HTTP_ERROR",
                    status_code=502,
                ) from exc
            except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
                raise AiPermanentError(
                    "LocalAI returned an invalid keyword response envelope.",
                    code="LOCALAI_INVALID_RESPONSE",
                    status_code=502,
                ) from exc
        raise AiTransientError(
            "LocalAI keyword request failed after retries.",
            code="LOCALAI_UNAVAILABLE",
            status_code=503,
        ) from last_error
