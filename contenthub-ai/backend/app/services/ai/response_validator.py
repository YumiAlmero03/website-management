from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from app.models.platform import Platform
from app.models.social_profile import SocialProfile
from app.services.ai.exceptions import AiResponseValidationError

_URL_REGEX = re.compile(r"https?://\S+")


class WebsiteKnowledgeAnalysisOutput(BaseModel):
    business_overview: str = Field(min_length=10, max_length=4000)
    products_and_services: list[str] = Field(default_factory=list)
    main_features: list[str] = Field(default_factory=list)
    target_audience: str | None = None
    recommended_writing_tone: str | None = None
    main_keywords: list[str] = Field(default_factory=list)
    content_pillars: list[str] = Field(default_factory=list)
    relevant_publishing_restrictions: str | None = None


class ContentSummaryOutput(BaseModel):
    summary: str = Field(min_length=10, max_length=2500)
    key_points: list[str] = Field(default_factory=list)
    needs_fact_review: bool = False
    review_note: str | None = None


class GeneratedProfileDraftItem(BaseModel):
    social_profile_id: int
    platform: str
    title: str | None = None
    caption: str = Field(min_length=5, max_length=20000)
    hashtags: list[str] = Field(default_factory=list)
    cta: str | None = None
    needs_review: bool = False
    review_note: str | None = None


class MultiProfileSocialBatchOutput(BaseModel):
    drafts: list[GeneratedProfileDraftItem] = Field(min_length=1)


@dataclass(frozen=True)
class ValidatedAssembledDraft:
    social_profile_id: int
    platform_key: str
    title: str | None
    caption: str
    assembled_content: str
    hashtags: list[str]
    cta_text: str | None
    source_url: str | None
    character_count: int
    character_limit: int | None
    validation_warnings: list[str]


def parse_structured_response(raw_text: str, schema_cls: type[BaseModel]) -> BaseModel:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AiResponseValidationError(f"Gemini output is not valid JSON: {exc}") from exc

    try:
        return schema_cls.model_validate(data)
    except ValidationError as exc:
        raise AiResponseValidationError(
            f"Gemini JSON failed {schema_cls.__name__} validation: {exc.error_count()} error(s)."
        ) from exc


def measure_platform_character_count(text: str, platform: Platform) -> int:
    """Compute platform-aware character length (e.g., X/Twitter URL shortener counting)."""
    if platform.url_counts_as_chars is not None and platform.url_counts_as_chars > 0:
        url_len = platform.url_counts_as_chars

        def _repl(_match: re.Match[str]) -> str:
            return "x" * url_len

        normalized = _URL_REGEX.sub(_repl, text)
        return len(normalized)
    return len(text)


def sanitize_hashtags(
    raw_hashtags: list[str],
    *,
    restricted_keywords: list[str],
    include_hashtags: bool,
    platform: Platform,
) -> list[str]:
    if not include_hashtags or not platform.supports_hashtags:
        return []
    restricted_lower = {k.strip().lower() for k in restricted_keywords if k.strip()}
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in raw_hashtags:
        norm = tag.strip().lstrip("#")
        if not norm:
            continue
        if any(r in norm.lower() for r in restricted_lower):
            continue
        formatted = f"#{norm.replace(' ', '')}"
        if formatted.lower() in seen:
            continue
        seen.add(formatted.lower())
        cleaned.append(formatted)
    return cleaned[:10]


def assemble_and_validate_draft(
    *,
    item: GeneratedProfileDraftItem,
    profile: SocialProfile,
    platform: Platform,
    source_url: str | None,
    website_default_hashtags: list[str],
    website_restricted_keywords: list[str],
) -> ValidatedAssembledDraft:
    caption = item.caption.strip()
    hashtags = sanitize_hashtags(
        item.hashtags or list(profile.default_hashtags or []) or website_default_hashtags,
        restricted_keywords=website_restricted_keywords,
        include_hashtags=profile.include_hashtags,
        platform=platform,
    )
    cta_text = (item.cta or profile.default_cta or "").strip() or None
    if not platform.supports_cta:
        cta_text = None

    effective_source_url = (
        source_url if (profile.include_source_url and platform.supports_source_url) else None
    )

    warnings: list[str] = []
    if item.needs_review and item.review_note:
        warnings.append(item.review_note.strip()[:220])
    if platform.platform_key == "instagram" and effective_source_url:
        warnings.append(
            "Instagram caption URLs are not automatically clickable; "
            "share in bio or Story link if needed."
        )
    if platform.platform_key == "google_business_profile":
        warnings.append(
            "Verify Google Business Profile promotional & category compliance before publishing."
        )

    parts: list[str] = [caption]
    if cta_text and cta_text.lower() not in caption.lower():
        parts.append(cta_text)
    if effective_source_url and effective_source_url not in caption:
        parts.append(effective_source_url)
    if hashtags:
        tag_str = " ".join(hashtags)
        if tag_str.lower() not in caption.lower():
            parts.append(tag_str)

    assembled = "\n\n".join(parts).strip()
    limit = (
        profile.character_limit
        if profile.character_limit is not None
        else platform.default_max_chars
    )
    char_count = measure_platform_character_count(assembled, platform)

    if limit is not None and char_count > limit:
        # Preserve mandatory source URL cleanly when tightening over-budget AI drafts,
        # and still flag an explicit validation warning if tight.
        reserve = (len(effective_source_url) + 2) if effective_source_url else 0
        if platform.url_counts_as_chars and effective_source_url:
            reserve = platform.url_counts_as_chars + 2
        if limit - reserve >= 40 and caption:
            trimmed_budget = max(20, limit - reserve - 3)
            trimmed_caption = caption[:trimmed_budget].rstrip() + "..."
            re_parts = [trimmed_caption]
            if effective_source_url:
                re_parts.append(effective_source_url)
            assembled = "\n\n".join(re_parts).strip()
            char_count = measure_platform_character_count(assembled, platform)
            warnings.append(
                f"Trimmed assembled draft to fit {platform.display_name} {limit}-character limit."
            )
        if char_count > limit:
            raise AiResponseValidationError(
                f"Generated content ({char_count} chars) exceeds limit ({limit}) "
                f"for profile '{profile.profile_name}'."
            )

    # Check restricted keywords against final assembled text
    lowered = assembled.lower()
    for restricted in website_restricted_keywords:
        r = restricted.strip().lower()
        if r and r in lowered:
            warnings.append(f"Contains restricted term '{restricted.strip()}'; requires review.")

    pin_title = item.title.strip()[:250] if (platform.supports_title and item.title) else None

    return ValidatedAssembledDraft(
        social_profile_id=profile.id,
        platform_key=platform.platform_key,
        title=pin_title,
        caption=caption,
        assembled_content=assembled,
        hashtags=hashtags,
        cta_text=cta_text,
        source_url=effective_source_url,
        character_count=char_count,
        character_limit=limit,
        validation_warnings=warnings,
    )


def validate_multi_profile_batch(
    *,
    output: MultiProfileSocialBatchOutput,
    expected_profiles: dict[int, tuple[SocialProfile, Platform]],
    source_url: str | None,
    website_default_hashtags: list[str],
    website_restricted_keywords: list[str],
) -> tuple[dict[int, ValidatedAssembledDraft], dict[int, str]]:
    """Validate batch drafts by social_profile_id, rejecting unknown/foreign IDs."""
    for item in output.drafts:
        if item.social_profile_id not in expected_profiles:
            raise AiResponseValidationError(
                f"AI response returned unexpected social_profile_id={item.social_profile_id} "
                "outside requested website destinations."
            )

    accepted: dict[int, ValidatedAssembledDraft] = {}
    errors: dict[int, str] = {}

    for item in output.drafts:
        pid = item.social_profile_id
        if pid in accepted:
            continue
        profile, platform = expected_profiles[pid]
        try:
            accepted[pid] = assemble_and_validate_draft(
                item=item,
                profile=profile,
                platform=platform,
                source_url=source_url,
                website_default_hashtags=website_default_hashtags,
                website_restricted_keywords=website_restricted_keywords,
            )
        except AiResponseValidationError as exc:
            errors[pid] = str(exc)

    for pid in expected_profiles:
        if pid not in accepted and pid not in errors:
            errors[pid] = "Gemini response omitted draft for this configured social profile."

    return accepted, errors
