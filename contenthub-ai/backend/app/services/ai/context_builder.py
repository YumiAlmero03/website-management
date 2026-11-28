from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from app.models.website import Website
from app.models.website_content import WebsiteContent
from app.models.website_knowledge_profile import WebsiteKnowledgeProfile
from app.services.content.optimizer import build_optimized_context

ALLOWED_CONTEXT_MODES: tuple[str, ...] = ("metadata_only", "optimized", "full")

_ABOUT_HINTS = ("about", "company", "who-we-are", "overview", "story")
_PRODUCT_HINTS = ("product", "service", "feature", "game", "casino", "sport", "pricing", "plan")
_POLICY_HINTS = ("terms", "privacy", "policy", "responsible", "disclaimer", "faq", "rules")


@dataclass(frozen=True)
class PreparedContextPackage:
    text: str
    context_mode: str
    truncated: bool
    truncation_note: str | None


def sanitize_untrusted_text(raw: str | None) -> str:
    """Strip control sequences and prompt-delimiter lookalikes from scraped website content."""
    if not raw:
        return ""
    cleaned = raw.replace("\x00", "")
    # Neutralize explicit XML-like prompt wrapper tags so scraped text cannot escape boundaries
    cleaned = re.sub(r"(?i)</?\s*source_content\s*>", "[source_tag]", cleaned)
    cleaned = re.sub(r"(?i)</?\s*system_instructions\s*>", "[system_tag]", cleaned)
    return cleaned.strip()


def format_knowledge_summary(
    website: Website,
    knowledge: WebsiteKnowledgeProfile | None,
) -> str:
    if knowledge is None:
        lines = [
            f"Brand: {website.brand_name or website.name}",
            f"Domain: https://{website.domain}/",
            f"Primary Language: {website.primary_language}",
        ]
        if website.brand_description:
            lines.append(f"Description: {website.brand_description[:500]}")
        if website.target_audience:
            lines.append(f"Audience: {website.target_audience}")
        if website.target_country:
            lines.append(f"Target Country: {website.target_country}")
        if website.tone:
            lines.append(f"Tone: {website.tone}")
        if website.restricted_keywords:
            lines.append(f"Restricted Keywords: {', '.join(website.restricted_keywords[:12])}")
        if website.writing_guidelines:
            lines.append(f"Writing Guidelines: {website.writing_guidelines[:400]}")
        return "\n".join(lines)

    lines = [
        f"Brand: {knowledge.brand_name} ({knowledge.website_category or 'General'})",
        f"Primary Language: {knowledge.primary_language}",
    ]
    if knowledge.business_overview or knowledge.brand_description:
        overview = (knowledge.business_overview or knowledge.brand_description or "")[:650]
        lines.append(f"Overview: {overview}")
    if knowledge.products_and_services:
        lines.append(f"Products/Services: {', '.join(knowledge.products_and_services[:8])}")
    if knowledge.main_features:
        lines.append(f"Key Features: {', '.join(knowledge.main_features[:8])}")
    if knowledge.target_audience:
        lines.append(f"Target Audience: {knowledge.target_audience}")
    if knowledge.target_country:
        lines.append(f"Target Country: {knowledge.target_country}")
    if knowledge.recommended_writing_tone:
        lines.append(f"Recommended Tone: {knowledge.recommended_writing_tone}")
    if knowledge.content_pillars:
        lines.append(f"Content Pillars: {', '.join(knowledge.content_pillars[:6])}")
    if knowledge.relevant_publishing_restrictions:
        lines.append(
            f"Publishing Restrictions: {knowledge.relevant_publishing_restrictions[:450]}"
        )
    if knowledge.administrator_notes:
        lines.append(f"Admin Notes: {knowledge.administrator_notes[:350]}")
    return "\n".join(lines)


def prepare_article_context(
    content: WebsiteContent,
    *,
    context_mode: str = "optimized",
    max_optimized_chars: int = 4000,
    max_full_chars: int = 12000,
) -> PreparedContextPackage:
    mode = context_mode if context_mode in ALLOWED_CONTEXT_MODES else "optimized"
    safe_title = sanitize_untrusted_text(content.title)
    safe_meta = sanitize_untrusted_text(content.meta_description)
    safe_kw = [sanitize_untrusted_text(k) for k in (content.keywords or []) if k]

    if mode == "metadata_only":
        parts = [
            f"Title: {safe_title}",
            f"Type: {content.content_type}",
            f"URL: {content.canonical_url}",
        ]
        if safe_meta:
            parts.append(f"Meta Description: {safe_meta[:400]}")
        if safe_kw:
            parts.append(f"Keywords: {', '.join(safe_kw[:12])}")
        text = "\n".join(parts)
        return PreparedContextPackage(
            text=text, context_mode=mode, truncated=False, truncation_note=None
        )

    if mode == "full":
        body = sanitize_untrusted_text(
            content.markdown_content or content.extracted_content or content.optimized_context
        )
        header = (
            f"Title: {safe_title}\n"
            f"URL: {content.canonical_url}\n"
            f"Language: {content.language or 'en'}\n"
            f"Meta Description: {safe_meta[:350]}\n\n"
        )
        full_text = header + body
        if len(full_text) > max_full_chars:
            clipped = full_text[:max_full_chars].rstrip()
            note = (
                f"Full content trimmed from {len(full_text)} to {max_full_chars} characters "
                "for token safety."
            )
            return PreparedContextPackage(
                text=clipped, context_mode=mode, truncated=True, truncation_note=note
            )
        return PreparedContextPackage(
            text=full_text, context_mode=mode, truncated=False, truncation_note=None
        )

    # Default "optimized": reuse Phase 2.1 Python-compressed context or compute locally without AI
    compact = sanitize_untrusted_text(content.optimized_context)
    if not compact:
        compact = build_optimized_context(
            title=safe_title,
            canonical_url=content.canonical_url,
            meta_description=safe_meta,
            markdown_content=sanitize_untrusted_text(
                content.markdown_content or content.extracted_content or ""
            ),
            keywords=safe_kw,
            published_at=content.published_at,
            language=content.language,
            max_chars=max_optimized_chars,
        )
    if len(compact) > max_optimized_chars:
        return PreparedContextPackage(
            text=compact[:max_optimized_chars].rstrip(),
            context_mode="optimized",
            truncated=True,
            truncation_note=(
                f"Optimized context compressed to {max_optimized_chars} characters."
            ),
        )
    return PreparedContextPackage(
        text=compact,
        context_mode="optimized",
        truncated=False,
        truncation_note=None,
    )


def select_knowledge_sources(
    website: Website,
    contents: list[WebsiteContent],
    *,
    max_items: int = 12,
    max_total_chars: int = 9000,
) -> tuple[str, list[dict[str, Any]], list[dict[str, str]], str]:
    """Select compact prioritized website content for knowledge synthesis.

    Avoids sending all discovered URLs and large HTML pages to Gemini.
    """
    extracted = [c for c in contents if c.extraction_status == "extracted" and not c.is_excluded]

    def _priority(c: WebsiteContent) -> tuple[int, int]:
        url_l = c.canonical_url.lower()
        title_l = c.title.lower()
        if c.content_type == "homepage":
            return (1, -c.word_count)
        if any(h in url_l or h in title_l for h in _ABOUT_HINTS):
            return (2, -c.word_count)
        if any(h in url_l or h in title_l for h in _PRODUCT_HINTS):
            return (3, -c.word_count)
        if c.content_type == "page" and not any(h in url_l or h in title_l for h in _POLICY_HINTS):
            return (4, -c.word_count)
        if any(h in url_l or h in title_l for h in _POLICY_HINTS):
            return (5, -c.word_count)
        if c.content_type == "blog_post":
            return (6, -c.word_count)
        return (7, -c.word_count)

    prioritized = sorted(extracted, key=_priority)[:max_items]

    admin_lines = [
        f"Website Name: {website.name}",
        f"Brand Name: {website.brand_name or website.name}",
        f"Domain: https://{website.domain}/",
        f"Primary Language: {website.primary_language}",
    ]
    if website.secondary_languages:
        admin_lines.append(f"Secondary Languages: {', '.join(website.secondary_languages)}")
    if website.brand_description:
        admin_lines.append(f"Admin Brand Description: {website.brand_description}")
    if website.target_audience:
        admin_lines.append(f"Admin Target Audience: {website.target_audience}")
    if website.target_country:
        admin_lines.append(f"Admin Target Country: {website.target_country}")
    if website.tone:
        admin_lines.append(f"Admin Preferred Tone: {website.tone}")
    if website.target_keywords:
        admin_lines.append(f"Admin Target Keywords: {', '.join(website.target_keywords)}")
    if website.keyword_bank:
        admin_lines.append(
            f"Website Keyword Bank (reference for new blogs/articles): {', '.join(website.keyword_bank)}"
        )
    if website.restricted_keywords:
        admin_lines.append(f"Admin Restricted Keywords: {', '.join(website.restricted_keywords)}")
    if website.writing_guidelines:
        admin_lines.append(f"Admin Writing Guidelines: {website.writing_guidelines}")
    if website.ai_instructions:
        admin_lines.append(f"Admin AI Instructions: {website.ai_instructions}")

    chunks: list[str] = ["[Administrator Website Metadata]\n" + "\n".join(admin_lines)]
    source_refs: list[dict[str, Any]] = []
    internal_links: list[dict[str, str]] = []
    fp_parts: list[str] = [
        website.brand_name or website.name,
        website.brand_description or "",
        website.writing_guidelines or "",
        website.ai_instructions or "",
    ]

    used_chars = len(chunks[0])
    for item in prioritized:
        snippet = sanitize_untrusted_text(
            item.optimized_context or item.meta_description or item.markdown_content or ""
        )[:750]
        entry = (
            f"[{item.content_type.upper()}] {sanitize_untrusted_text(item.title)} "
            f"({item.canonical_url})\n{snippet}"
        )
        if used_chars + len(entry) > max_total_chars and source_refs:
            continue
        chunks.append(entry)
        used_chars += len(entry)
        source_refs.append(
            {
                "content_id": item.id,
                "title": item.title[:200],
                "url": item.canonical_url,
                "content_type": item.content_type,
                "content_hash": item.content_hash,
            }
        )
        fp_parts.append(f"{item.id}:{item.content_hash}")
        if (
            item.content_type in {"homepage", "page", "game_page", "blog_index"}
            and len(internal_links) < 10
        ):
            internal_links.append(
                {
                    "title": item.title[:120],
                    "url": item.canonical_url,
                    "content_type": item.content_type,
                }
            )

    fingerprint = hashlib.sha256("|".join(fp_parts).encode("utf-8")).hexdigest()
    return "\n\n---\n\n".join(chunks), source_refs, internal_links, fingerprint
