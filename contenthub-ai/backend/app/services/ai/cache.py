from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from app.models.ai_response_cache import AiResponseCache
from app.models.base import utc_now_naive
from app.repositories.ai_repo import AiRepositoryProtocol


def compute_sha256_json(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_cache_key(
    *,
    website_id: int,
    ai_provider_id: int,
    model_name: str,
    task_type: str,
    prompt_template_id: int | None,
    prompt_version: int,
    source_content_hash: str,
    knowledge_version: int,
    profile_config_hash: str,
    language: str,
    context_mode: str,
    generation_settings: dict[str, Any],
    keyword_mapping_fingerprint: str = "",
    schema_version: str = "v1",
) -> str:
    """Compute a strictly website-scoped deterministic SHA-256 AI response cache key."""
    key_material = {
        "website_id": website_id,
        "ai_provider_id": ai_provider_id,
        "model_name": model_name,
        "task_type": task_type,
        "prompt_template_id": prompt_template_id,
        "prompt_version": prompt_version,
        "source_content_hash": source_content_hash,
        "knowledge_version": knowledge_version,
        "profile_config_hash": profile_config_hash,
        "language": language.lower(),
        "context_mode": context_mode,
        "generation_settings": generation_settings,
        "keyword_mapping_fingerprint": keyword_mapping_fingerprint,
        "schema_version": schema_version,
    }
    return compute_sha256_json(key_material)


class AiResponseCacheService:
    def __init__(self, *, ai_repo: AiRepositoryProtocol, default_ttl_days: int = 30) -> None:
        self.ai_repo = ai_repo
        self.default_ttl_days = default_ttl_days

    def get_valid(
        self,
        *,
        cache_key_hash: str,
        website_id: int,
    ) -> AiResponseCache | None:
        entry = self.ai_repo.get_cache_entry(cache_key_hash)
        if entry is None:
            return None
        # Strict website isolation guard
        if entry.website_id != website_id:
            return None
        return entry

    def store(
        self,
        *,
        cache_key_hash: str,
        ai_provider_id: int,
        website_id: int,
        website_content_id: int | None,
        prompt_template_id: int | None,
        task_type: str,
        model_name: str,
        prompt_version: int,
        context_mode: str,
        language: str,
        source_content_hash: str,
        profile_config_hash: str,
        generation_settings: dict[str, Any],
        response_json: dict[str, Any],
        input_tokens: int | None,
        output_tokens: int | None,
        schema_version: str = "v1",
        ttl_days: int | None = None,
    ) -> AiResponseCache:
        ttl = ttl_days if ttl_days is not None else self.default_ttl_days
        now = utc_now_naive()
        entry = self.ai_repo.upsert_cache_entry(
            {
                "cache_key_hash": cache_key_hash,
                "ai_provider_id": ai_provider_id,
                "website_id": website_id,
                "website_content_id": website_content_id,
                "prompt_template_id": prompt_template_id,
                "task_type": task_type,
                "model_name": model_name,
                "prompt_version": prompt_version,
                "context_mode": context_mode,
                "language": language,
                "schema_version": schema_version,
                "source_content_hash": source_content_hash,
                "profile_config_hash": profile_config_hash,
                "generation_settings_json": generation_settings,
                "response_json": response_json,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "hit_count": 0,
                "last_hit_at": None,
                "expires_at": now + timedelta(days=max(1, ttl)),
            }
        )
        return entry
