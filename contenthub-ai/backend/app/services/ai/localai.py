from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.services.ai.exceptions import AiPermanentError, AiTransientError
from app.services.ai.provider import ProviderModelDescriptor, ProviderTestResult


class LocalAiKeywordOutput(BaseModel):
    focus_keyphrase: str = Field(min_length=2, max_length=120)
    secondary_keywords: list[str] = Field(default_factory=list, max_length=12)


def normalize_localai_base_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    if not value:
        return "http://127.0.0.1:8080"
    if value.endswith("/v1"):
        return value[:-3].rstrip("/")
    return value


class LocalAiProvider:
    """OpenAI-compatible HTTPX client restricted to LocalAI keyword assistance."""

    def _request(self, base_url: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
        root = normalize_localai_base_url(base_url)
        url = f"{root}/v1{path}"
        with httpx.Client(timeout=kwargs.pop("timeout_seconds", 60), follow_redirects=False) as client:
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
        return ProviderTestResult(
            connected=True,
            selected_model=selected_model,
            model_available=available,
            latency_ms=int((time.monotonic() - started) * 1000),
            discovered_models=models,
            error_detail=None if available else "Selected model is not in the installed model list.",
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
    ) -> tuple[LocalAiKeywordOutput, str]:
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
        for attempt in range(max_retries + 1):
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
                text = data["choices"][0]["message"]["content"]
                parsed = LocalAiKeywordOutput.model_validate_json(text)
                return parsed, model_name
            except httpx.TimeoutException as exc:
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc
            except (httpx.HTTPStatusError, KeyError, ValueError) as exc:
                raise AiPermanentError(
                    f"LocalAI keyword response was invalid: {exc}",
                    code="LOCALAI_INVALID_RESPONSE",
                    status_code=502,
                ) from exc
        raise AiTransientError(
            "LocalAI keyword request failed after retries.",
            code="LOCALAI_UNAVAILABLE",
            status_code=503,
        ) from last_error
