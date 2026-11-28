from __future__ import annotations

import math

from app.services.ai.provider import ProviderGenerationResult


def estimate_tokens_from_text(text: str | None) -> int:
    """Fast heuristic token estimate (~4 chars/token) explicitly distinct from measured tokens."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def resolve_usage_fields(
    *,
    estimated_input_tokens: int,
    provider_result: ProviderGenerationResult | None = None,
    cache_hit: bool = False,
) -> dict[str, int | str | None]:
    """Separate application-estimated input tokens from provider-measured token counts.

    Unknown provider token metrics remain None (unknown) rather than fabricated as zero.
    """
    if cache_hit:
        return {
            "estimated_input_tokens": estimated_input_tokens,
            "measured_input_tokens": None,
            "measured_output_tokens": None,
            "total_measured_tokens": None,
            "token_usage_status": "cached",
        }

    if provider_result is None or not provider_result.raw_usage_available:
        return {
            "estimated_input_tokens": estimated_input_tokens,
            "measured_input_tokens": None,
            "measured_output_tokens": None,
            "total_measured_tokens": None,
            "token_usage_status": "unknown",
        }

    in_tok = provider_result.measured_input_tokens
    out_tok = provider_result.measured_output_tokens
    tot_tok = provider_result.total_measured_tokens
    if tot_tok is None and in_tok is not None and out_tok is not None:
        tot_tok = in_tok + out_tok

    return {
        "estimated_input_tokens": estimated_input_tokens,
        "measured_input_tokens": in_tok,
        "measured_output_tokens": out_tok,
        "total_measured_tokens": tot_tok,
        "token_usage_status": "measured",
    }
