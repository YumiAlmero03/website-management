from __future__ import annotations

from app.services.ai.provider import ProviderModelDescriptor

DEPRECATED_MODEL_PREFIXES: tuple[str, ...] = (
    "gemini-1.0",
    "gemini-1.5",
    "gemini-2.0",
    "gemini-2.5",
    "gemini-pro",
)

NON_TEXT_GENERATION_HINTS: tuple[str, ...] = (
    "embedding",
    "imagen",
    "veo",
    "lyria",
    "tts",
    "transcribe",
    "image",
    "genie",
    "aqa",
    "bisect",
    "decision",
)


def normalize_model_name(raw_name: str) -> str:
    cleaned = raw_name.strip()
    if cleaned.startswith("models/"):
        cleaned = cleaned[len("models/") :]
    return cleaned


def is_flash_preferred_model(model_name: str) -> bool:
    lower = normalize_model_name(model_name).lower()
    if any(lower.startswith(dep) for dep in DEPRECATED_MODEL_PREFIXES):
        return False
    return "flash" in lower or "hydrogen" in lower


def is_compatible_text_model(model: ProviderModelDescriptor) -> bool:
    """Filter models retrieved from Gemini API for text/JSON generation compatibility."""
    short = normalize_model_name(model.name).lower()
    if any(short.startswith(dep) for dep in DEPRECATED_MODEL_PREFIXES):
        return False
    if any(hint in short for hint in NON_TEXT_GENERATION_HINTS):
        return False

    actions = {a.lower() for a in model.supported_actions}
    # If the API returned supported_actions, verify generation compatibility
    if actions and not (
        "generatecontent" in actions
        or "interactions" in actions
        or "createinteraction" in actions
    ):
        return False
    return "gemini" in short or "gemma" in short


def sort_models_free_first(models: list[ProviderModelDescriptor]) -> list[ProviderModelDescriptor]:
    """Order compatible models placing Flash-Lite / Flash options first without hiding others."""

    def _rank(m: ProviderModelDescriptor) -> tuple[int, str]:
        lower = normalize_model_name(m.name).lower()
        if "flash-lite" in lower:
            return (0, lower)
        if "flash" in lower or "hydrogen" in lower:
            return (1, lower)
        if "argon" in lower or "neon" in lower:
            return (2, lower)
        return (3, lower)

    compatible = [m for m in models if is_compatible_text_model(m)]
    compatible.sort(key=_rank)
    return compatible
