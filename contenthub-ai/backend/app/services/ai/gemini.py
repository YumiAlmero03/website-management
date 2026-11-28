from __future__ import annotations

import contextlib
import time
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.core.logging import redact_text
from app.services.ai.exceptions import AiPermanentError, AiResponseValidationError, AiTransientError
from app.services.ai.model_registry import (
    is_flash_preferred_model,
    normalize_model_name,
    sort_models_free_first,
)
from app.services.ai.provider import (
    GENERATION_PROBE_PROMPT,
    ProviderGenerationResult,
    ProviderModelDescriptor,
    ProviderTestResult,
)


def _sanitized_error_message(exc: Exception) -> str:
    return redact_text(str(exc))[:450] or type(exc).__name__


def _interaction_result(
    interaction: Any, model_name: str, started: float
) -> ProviderGenerationResult:
    usage = getattr(interaction, "usage", None)
    input_tokens = getattr(usage, "total_input_tokens", None)
    output_tokens = getattr(usage, "total_output_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    return ProviderGenerationResult(
        raw_text=str(getattr(interaction, "output_text", None) or "").strip(),
        model_name=model_name,
        latency_ms=int((time.monotonic() - started) * 1000),
        measured_input_tokens=int(input_tokens) if input_tokens is not None else None,
        measured_output_tokens=int(output_tokens) if output_tokens is not None else None,
        total_measured_tokens=int(total_tokens) if total_tokens is not None else None,
        raw_usage_available=any(
            value is not None for value in (input_tokens, output_tokens, total_tokens)
        ),
    )


class GeminiSdkProvider:
    """Official Google Gen AI SDK adapter using the current Interactions & Models surfaces."""

    @staticmethod
    def _create_client(*, api_key: str, timeout_seconds: int) -> genai.Client:
        if not api_key or not api_key.strip():
            raise AiPermanentError(
                "Gemini API key is missing for this provider configuration.",
                code="MISSING_API_KEY",
            )
        # google-genai HttpOptions.timeout expects milliseconds (or httpx.Timeout on interactions)
        return genai.Client(
            api_key=api_key.strip(),
            http_options={"timeout": max(5, timeout_seconds) * 1000},
        )

    @staticmethod
    def _raise_mapped_sdk_error(exc: Exception) -> None:
        sanitized = _sanitized_error_message(exc)
        if isinstance(exc, genai_errors.APIError):
            code = getattr(exc, "code", None)
            if code in {401, 403}:
                raise AiPermanentError(
                    f"Gemini API authentication rejected: {sanitized}",
                    code="GEMINI_AUTH_ERROR",
                    status_code=401,
                ) from exc
            if code == 404:
                raise AiPermanentError(
                    f"Requested Gemini model or endpoint was not found: {sanitized}",
                    code="GEMINI_MODEL_NOT_FOUND",
                    status_code=404,
                ) from exc
            if code == 400:
                raise AiPermanentError(
                    f"Gemini rejected request parameters: {sanitized}",
                    code="GEMINI_BAD_REQUEST",
                    status_code=400,
                ) from exc
            if code == 429:
                raise AiTransientError(
                    f"Gemini provider rate limit or quota reached: {sanitized}",
                    code="GEMINI_RATE_LIMITED",
                    status_code=429,
                ) from exc
            if code is not None and code >= 500:
                raise AiTransientError(
                    f"Gemini service error (HTTP {code}): {sanitized}",
                    code="GEMINI_SERVER_ERROR",
                    status_code=503,
                ) from exc
            raise AiTransientError(
                f"Gemini API error: {sanitized}",
                code="GEMINI_API_ERROR",
                status_code=502,
            ) from exc

        if isinstance(exc, httpx.TimeoutException | TimeoutError):
            raise AiTransientError(
                f"Gemini API request timed out: {sanitized}",
                code="GEMINI_TIMEOUT",
                status_code=504,
            ) from exc

        if isinstance(exc, httpx.TransportError):
            raise AiTransientError(
                f"Network error contacting Gemini API: {sanitized}",
                code="GEMINI_NETWORK_ERROR",
                status_code=503,
            ) from exc

        raise AiTransientError(
            f"Unexpected Gemini client error: {sanitized}",
            code="GEMINI_UNEXPECTED_ERROR",
            status_code=502,
        ) from exc

    def list_models(
        self, *, api_key: str, timeout_seconds: int = 45
    ) -> list[ProviderModelDescriptor]:
        client = self._create_client(api_key=api_key, timeout_seconds=timeout_seconds)
        descriptors: list[ProviderModelDescriptor] = []
        try:
            for m in client.models.list():
                raw_name = str(getattr(m, "name", "") or "")
                short_name = normalize_model_name(raw_name)
                if not short_name:
                    continue
                descriptors.append(
                    ProviderModelDescriptor(
                        name=short_name,
                        display_name=str(getattr(m, "display_name", None) or short_name),
                        description=getattr(m, "description", None),
                        input_token_limit=getattr(m, "input_token_limit", None),
                        output_token_limit=getattr(m, "output_token_limit", None),
                        supported_actions=tuple(getattr(m, "supported_actions", None) or ()),
                        is_flash_recommended=is_flash_preferred_model(short_name),
                    )
                )
        except Exception as exc:
            self._raise_mapped_sdk_error(exc)
        return sort_models_free_first(descriptors)

    def test_connection(
        self,
        *,
        api_key: str,
        selected_model: str,
        timeout_seconds: int = 45,
        verify_generation: bool = False,
    ) -> ProviderTestResult:
        started = time.monotonic()
        target_model = normalize_model_name(selected_model)
        try:
            models = self.list_models(api_key=api_key, timeout_seconds=timeout_seconds)
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            return ProviderTestResult(
                connected=False,
                selected_model=target_model,
                model_available=False,
                latency_ms=latency,
                discovered_models=[],
                error_detail=_sanitized_error_message(exc),
            )

        available_names = {normalize_model_name(m.name) for m in models}
        model_available = target_model in available_names
        probe_result: ProviderGenerationResult | None = None

        if verify_generation and model_available:
            try:
                client = self._create_client(api_key=api_key, timeout_seconds=timeout_seconds)
                probe_started = time.monotonic()
                interaction = client.interactions.create(
                    model=target_model,
                    input=GENERATION_PROBE_PROMPT,
                    generation_config={"max_output_tokens": 8, "temperature": 0.0},
                    store=False,
                    timeout=float(timeout_seconds),
                )
                probe_result = _interaction_result(interaction, target_model, probe_started)
            except Exception as exc:
                latency = int((time.monotonic() - started) * 1000)
                return ProviderTestResult(
                    connected=False,
                    selected_model=target_model,
                    model_available=model_available,
                    latency_ms=latency,
                    discovered_models=models,
                    error_detail=_sanitized_error_message(exc),
                )

        latency = int((time.monotonic() - started) * 1000)
        return ProviderTestResult(
            connected=True,
            selected_model=target_model,
            model_available=model_available,
            latency_ms=latency,
            discovered_models=models,
            error_detail=(
                None
                if model_available
                else f"Connected, but selected model '{target_model}' was not in listed models."
            ),
            generation_probe_tokens=probe_result.total_measured_tokens if probe_result else None,
            generation_result=probe_result,
        )

    def count_tokens(
        self,
        *,
        api_key: str,
        model_name: str,
        system_instruction: str,
        user_prompt: str,
        timeout_seconds: int = 45,
    ) -> int | None:
        client = self._create_client(api_key=api_key, timeout_seconds=timeout_seconds)
        combined = f"{system_instruction}\n\n{user_prompt}".strip()
        with contextlib.suppress(Exception):
            resp = client.models.count_tokens(
                model=normalize_model_name(model_name),
                contents=combined,
            )
            total = getattr(resp, "total_tokens", None)
            return int(total) if total is not None else None
        return None

    def generate_structured(
        self,
        *,
        api_key: str,
        model_name: str,
        system_instruction: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        temperature: float = 0.4,
        max_output_tokens: int = 1500,
        timeout_seconds: int = 45,
    ) -> ProviderGenerationResult:
        client = self._create_client(api_key=api_key, timeout_seconds=timeout_seconds)
        target_model = normalize_model_name(model_name)
        started = time.monotonic()

        try:
            interaction = client.interactions.create(
                model=target_model,
                input=user_prompt,
                system_instruction=system_instruction,
                generation_config={
                    "temperature": float(temperature),
                    "max_output_tokens": int(max_output_tokens),
                },
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema,
                },
                store=False,
                timeout=float(timeout_seconds),
            )
        except Exception as exc:
            self._raise_mapped_sdk_error(exc)

        result = _interaction_result(interaction, target_model, started)
        if not result.raw_text:
            raise AiResponseValidationError("Gemini returned an empty response body.")
        return result

    def generate_image(
        self,
        *,
        api_key: str,
        model_name: str,
        prompt: str,
        timeout_seconds: int = 45,
    ) -> bytes:
        client = self._create_client(api_key=api_key, timeout_seconds=timeout_seconds)
        try:
            response = client.models.generate_images(
                model=model_name,
                prompt=prompt,
                config=genai_types.GenerateImagesConfig(number_of_images=1),
            )
        except Exception as exc:
            self._raise_mapped_sdk_error(exc)

        generated_images = getattr(response, "generated_images", None) or []
        image = getattr(generated_images[0], "image", None) if generated_images else None
        image_bytes = getattr(image, "image_bytes", None)
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise AiResponseValidationError("Gemini Imagen returned no image data.")
        return image_bytes
