from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

GENERATION_PROBE_PROMPT = "Reply with OK."


@dataclass(frozen=True)
class ProviderModelDescriptor:
    name: str
    display_name: str
    description: str | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    supported_actions: tuple[str, ...] = ()
    is_flash_recommended: bool = False


@dataclass(frozen=True)
class ProviderTestResult:
    connected: bool
    selected_model: str
    model_available: bool
    latency_ms: int | None
    discovered_models: list[ProviderModelDescriptor] = field(default_factory=list)
    error_detail: str | None = None
    generation_probe_tokens: int | None = None
    generation_result: ProviderGenerationResult | None = None


@dataclass(frozen=True)
class ProviderGenerationResult:
    raw_text: str
    model_name: str
    latency_ms: int
    measured_input_tokens: int | None = None
    measured_output_tokens: int | None = None
    total_measured_tokens: int | None = None
    raw_usage_available: bool = False


class AiProviderClientProtocol(Protocol):
    def list_models(
        self, *, api_key: str, timeout_seconds: int = 45
    ) -> list[ProviderModelDescriptor]:
        ...

    def test_connection(
        self,
        *,
        api_key: str,
        selected_model: str,
        timeout_seconds: int = 45,
        verify_generation: bool = False,
    ) -> ProviderTestResult:
        ...

    def count_tokens(
        self,
        *,
        api_key: str,
        model_name: str,
        system_instruction: str,
        user_prompt: str,
        timeout_seconds: int = 45,
    ) -> int | None:
        ...

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
        ...
