from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.core.exceptions import ValidationAppError
from app.models.base import utc_now_naive
from app.models.content_approval import ContentApproval
from app.models.content_keyword import ContentKeyword
from app.models.platform import Platform
from app.models.publishing import (
    PublicationRecord,
    PublishingJob,
    SocialPostMedia,
    SocialProfileConnection,
)
from app.models.social_post import SocialPost
from app.models.social_profile import SocialProfile
from app.models.website import Website
from app.services.ai.response_validator import measure_platform_character_count

RESTRICTED_GBP_SLUGS: frozenset[str] = frozenset(
    {"casino", "gambling", "betting", "adult", "sportsbook"}
)


def build_utm_url(source_url: str | None, utm_params: dict[str, str] | None) -> str | None:
    """Safely append sanitized utm_* parameters onto an http(s) source URL."""
    if not source_url or not source_url.strip():
        return None
    raw = source_url.strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationAppError("Source URL must be a valid http:// or https:// URL.")
    if not utm_params:
        return raw

    existing = dict(parse_qsl(parsed.query, keep_blank_values=False))
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
        val = (utm_params.get(key) or "").strip()
        if val:
            existing[key] = val[:150]
    new_query = urlencode(existing)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


def assemble_publish_caption(post: SocialPost) -> str:
    target_link = post.target_url_with_utm or post.source_url
    parts: list[str] = [post.caption.strip()]
    if post.cta_text and post.cta_text.strip().lower() not in post.caption.lower():
        parts.append(post.cta_text.strip())
    if target_link and target_link not in post.caption:
        parts.append(target_link)
    hashtags = [str(tag).strip() for tag in (post.hashtags_json or []) if str(tag).strip()]
    if hashtags:
        tag_str = " ".join(hashtags)
        if tag_str.lower() not in post.caption.lower():
            parts.append(tag_str)
    return "\n\n".join(p for p in parts if p).strip()


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_publish_preflight(
    *,
    website: Website | None,
    post: SocialPost,
    profile: SocialProfile | None,
    platform: Platform | None,
    connection: SocialProfileConnection | None,
    content_approval: ContentApproval | None = None,
    content_keyword: ContentKeyword | None = None,
    media_rows: list[SocialPostMedia] | None = None,
    existing_published_record: PublicationRecord | None = None,
    active_job: PublishingJob | None = None,
    daily_published_count: int = 0,
    latest_profile_publication: PublicationRecord | None = None,
    target_method: str | None = None,
    confirm_paid_api: bool = False,
) -> PreflightResult:
    """Enforce Section 14 pre-publish checklist and approval gates."""
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    def add_check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            errors.append(detail)

    # 1. Website is active
    site_ok = website is not None and website.status == "active"
    add_check(
        "website_active",
        site_ok,
        "Website is active." if site_ok else "Website must be active before publishing.",
    )

    # 2 & 3. Source content + keyword approval (separate from social draft approval)
    if post.website_content_id is not None:
        ca_ok = content_approval is not None and content_approval.status == "approved"
        add_check(
            "source_content_approved",
            ca_ok,
            (
                "Source website content is approved."
                if ca_ok
                else "Linked source website content must be approved in Content Approval first."
            ),
        )
        kw_ok = content_keyword is not None and content_keyword.approval_status == "approved"
        add_check(
            "keyword_mapping_approved",
            kw_ok,
            (
                "SEO keyword mapping is approved."
                if kw_ok
                else "Linked SEO keyword mapping must be approved before publishing."
            ),
        )

    # 4. Social draft approval & revision pinning
    draft_ok = post.status == "approved"
    if draft_ok and post.approved_revision_id is None and post.current_version < 1:
        draft_ok = False
    add_check(
        "social_draft_approved",
        draft_ok,
        (
            f"Social draft revision v{post.current_version} is approved."
            if draft_ok
            else "Social draft must be approved (editing invalidated prior approval or unapproved)."
        ),
    )

    # 5 & 6. Social profile active & publishing enabled
    prof_ok = profile is not None and profile.is_active
    add_check(
        "social_profile_active",
        prof_ok,
        "Social profile is active." if prof_ok else "Target social profile must be active.",
    )
    pub_enabled = profile is not None and profile.publishing_enabled
    add_check(
        "publishing_enabled",
        pub_enabled,
        (
            "Publishing is enabled for profile."
            if pub_enabled
            else "Publishing is currently disabled on this social profile."
        ),
    )

    # 7. Already published or active publish job prevention
    already_pub = (
        existing_published_record is not None
        or post.publishing_status in {"published", "manually_published"}
    )
    add_check(
        "not_already_published",
        not already_pub,
        (
            "Post has not been published yet."
            if not already_pub
            else "Post has already been published; duplicate publish blocked."
        ),
    )
    has_active_job = active_job is not None
    add_check(
        "no_active_job",
        not has_active_job,
        (
            "No active/pending publishing job exists."
            if not has_active_job
            else (
                f"Active job #{active_job.id} ({active_job.status}) already exists for this post."
            )
        ),
    )

    # 8. Method, credentials, permissions & eligibility
    method = (
        target_method or (profile.publishing_method if profile else "manual")
    ).strip().lower()
    caps = dict(platform.capabilities_json or {}) if platform else {}
    now = utc_now_naive()
    if method == "api":
        if platform and platform.platform_key == "custom_social":
            add_check(
                "api_supported",
                False,
                "Custom Social Platform supports Manual Publishing workflow only.",
            )
        has_creds = profile is not None and profile.credential_status != "not_configured"
        conn_ok = (
            connection is not None
            and connection.connection_status in {"connected", "configured", "expiring_soon"}
        )
        add_check(
            "credentials_valid",
            has_creds and conn_ok,
            (
                "Encrypted publishing credentials configured."
                if (has_creds and conn_ok)
                else "Valid connected API credentials are required for API publishing."
            ),
        )
        not_expired = (
            profile is None
            or profile.token_expires_at is None
            or profile.token_expires_at > now
        )
        add_check(
            "token_unexpired",
            not_expired,
            (
                "Access token has not expired."
                if not_expired
                else "Access token expired; refresh or reconnect account before publishing."
            ),
        )
        missing_scopes = list(connection.missing_scopes_json or []) if connection else []
        add_check(
            "permissions_granted",
            len(missing_scopes) == 0,
            (
                "Required platform permissions granted."
                if not missing_scopes
                else f"Missing required permissions: {', '.join(missing_scopes)}."
            ),
        )
        elig = connection.eligibility_status if connection else (
            profile.publishing_eligibility_status if profile else "unknown"
        )
        elig_ok = elig not in {"restricted", "blocked", "unsupported"}
        add_check(
            "destination_eligible",
            elig_ok,
            (
                "Destination eligible for content."
                if elig_ok
                else f"Destination marked '{elig}': "
                f"{(connection.eligibility_notes if connection else '') or 'policy restricted'}."
            ),
        )
        if caps.get("supports_target_selection") and connection is not None:
            has_target = bool(
                connection.target_resource_id
                or (profile and profile.external_account_id)
            )
            add_check(
                "target_selected",
                has_target,
                (
                    "Target Page / Account / Location / Board selected."
                    if has_target
                    else "Select a verified target resource (Page/Location/Board) "
                    "before API publish."
                ),
            )
        if caps.get("requires_paid_api_ack"):
            paid_ok = confirm_paid_api or (
                connection is not None and connection.allow_paid_publishing
            )
            add_check(
                "paid_api_authorized",
                paid_ok,
                (
                    "Paid X API authorization confirmed."
                    if paid_ok
                    else "X API requires pay-per-use credits/tier; "
                    "enable Paid API or publish manually."
                ),
            )
        if (
            platform
            and platform.platform_key == "google_business_profile"
            and website
            and any(
                k in f"{website.name} {website.domain}".lower()
                for k in RESTRICTED_GBP_SLUGS
            )
        ):
            warnings.append(
                "Website niche may be restricted under Google Business Profile policies; "
                "verify compliance."
            )
    else:
        checks.append(
            {
                "name": "manual_mode_ready",
                "passed": True,
                "detail": "Manual publishing mode requires no API credentials.",
            }
        )

    # 9. Media availability
    has_media = bool((media_rows and len(media_rows) > 0) or post.featured_media_id is not None)
    requires_media = bool(caps.get("requires_media")) or bool(
        profile and profile.default_media_required
    )
    if requires_media and method == "api":
        add_check(
            "required_media_available",
            has_media,
            (
                "Required media attachment present."
                if has_media
                else (
                    f"{platform.display_name if platform else 'Platform'} "
                    "requires an image attachment."
                )
            ),
        )

    # 10. Caption limit & restricted keywords
    final_caption = assemble_publish_caption(post)
    if platform is not None:
        char_len = measure_platform_character_count(final_caption, platform)
        limit = (
            profile.character_limit
            if profile and profile.character_limit is not None
            else platform.default_max_chars
        )
        within_limit = limit is None or char_len <= limit
        add_check(
            "caption_limit",
            within_limit,
            (
                f"Caption length ({char_len} chars) within limit ({limit or 'unlimited'})."
                if within_limit
                else f"Caption ({char_len} chars) exceeds platform limit ({limit})."
            ),
        )

    if website and website.restricted_keywords:
        lower_cap = final_caption.lower()
        hits = [kw for kw in website.restricted_keywords if kw.strip().lower() in lower_cap]
        add_check(
            "restricted_keywords",
            len(hits) == 0,
            (
                "No restricted keywords present."
                if not hits
                else f"Caption contains restricted keyword(s): {', '.join(hits)}."
            ),
        )

    # 11. Profile rate preferences (daily limit & minimum interval)
    if profile and profile.daily_publishing_limit is not None:
        under_daily = daily_published_count < profile.daily_publishing_limit
        add_check(
            "daily_limit",
            under_daily,
            (
                f"Daily publish count ({daily_published_count}/{profile.daily_publishing_limit})."
                if under_daily
                else (
                    f"Reached daily publishing limit ({profile.daily_publishing_limit}) "
                    "for profile."
                )
            ),
        )
    if (
        profile
        and profile.min_interval_minutes is not None
        and latest_profile_publication is not None
        and latest_profile_publication.published_at is not None
    ):
        min_next = latest_profile_publication.published_at + timedelta(
            minutes=profile.min_interval_minutes
        )
        interval_ok = now >= min_next
        add_check(
            "min_interval",
            interval_ok,
            (
                "Minimum interval between posts satisfied."
                if interval_ok
                else f"Wait until after {min_next.isoformat()}Z before next post on this profile."
            ),
        )

    return PreflightResult(
        ok=len(errors) == 0,
        checks=checks,
        errors=errors,
        warnings=warnings,
    )
