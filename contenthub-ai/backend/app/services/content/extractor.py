from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import trafilatura
from bs4 import BeautifulSoup

from app.config import Settings
from app.models.website_url_rule import WebsiteUrlRule
from app.services.content.duplicate import compute_content_hash
from app.services.content.keywords import extract_keywords
from app.services.content.markdown import (
    count_words,
    html_to_clean_markdown,
    normalize_markdown,
    sanitize_article_html,
)
from app.services.content.metadata import extract_html_metadata
from app.services.content.optimizer import build_optimized_context
from app.services.scanner.base import DiscoveredCandidate
from app.services.scanner.classifier import classify_url
from app.services.scanner.url_normalizer import hash_url, is_same_site, normalize_url


@dataclass
class ExtractedContent:
    title: str
    url: str
    canonical_url: str
    url_hash: str
    content_type: str
    classification_method: str
    h1_text: str | None
    author: str | None
    meta_description: str | None
    original_content: str
    extracted_content: str
    markdown_content: str
    optimized_context: str
    keywords: list[str]
    categories: list[str]
    tags: list[str]
    language: str | None
    content_hash: str
    word_count: int
    structured_data_json: dict[str, Any] = field(default_factory=dict)
    featured_image_url: str | None = None
    featured_image_alt: str | None = None
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    headings: list[str] = field(default_factory=list)


def _extract_main_html_trafilatura(raw_html: str, *, page_url: str) -> str | None:
    try:
        extracted = trafilatura.extract(
            raw_html,
            url=page_url,
            output_format="html",
            include_links=True,
            include_tables=True,
            include_formatting=True,
            include_comments=False,
            favor_precision=False,
        )
        if extracted and len(extracted.strip()) >= 80:
            return extracted
    except Exception:
        pass
    return None


def _extract_general_html_bs4(raw_html: str, *, include_sections: bool = False) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "form", "iframe", "svg"]):
        tag.decompose()
    if not include_sections:
        for tag in soup.find_all(["nav", "footer", "aside"]):
            tag.decompose()
        target = (
            soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.body
            or soup
        )
        return str(target)

    # For homepages and landing pages: keep content sections without footer noise.
    for tag in soup.find_all(["footer"]):
        tag.decompose()
    main_el = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    return str(main_el)


class ContentExtractionEngine:
    """Content-type-aware extractor via Trafilatura + BeautifulSoup4 fallback without AI calls."""

    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings

    def extract_from_html(
        self,
        raw_html: str,
        *,
        page_url: str,
        domain: str,
        candidate: DiscoveredCandidate | None = None,
        url_rules: list[WebsiteUrlRule] | None = None,
        manual_override_type: str | None = None,
        default_language: str | None = None,
    ) -> ExtractedContent:
        meta = extract_html_metadata(raw_html, page_url=page_url, domain=domain)

        chosen_url = page_url
        if meta.canonical_url:
            try:
                norm_canonical = normalize_url(meta.canonical_url, base_url=page_url)
                if is_same_site(norm_canonical, domain):
                    chosen_url = norm_canonical
            except ValueError:
                pass
        normalized_canonical = normalize_url(chosen_url, base_url=page_url)
        normalized_discovered = normalize_url(page_url, base_url=page_url)

        decision = classify_url(
            normalized_discovered,
            domain=domain,
            custom_rules=url_rules,
            jsonld_types=meta.jsonld_types,
            og_type=meta.og_type,
            source_methods=candidate.discovery_sources if candidate else None,
            manual_override_type=manual_override_type,
        )
        content_type = decision.content_type
        classification_method = decision.classification_method

        # Content-type-aware extraction strategy:
        # - Homepages/Pages preserve sections, headings, and landing copy even without <article>
        # - Blog Posts prioritize Trafilatura main article extraction + WP candidate HTML fallback
        # - Blog Index/Category/Tag/Archive preserve overview text & discovered linked URLs
        is_landing = content_type in {
            "homepage",
            "page",
            "custom",
            "blog_index",
            "category",
            "tag",
            "archive",
        }
        main_html: str | None = None
        if content_type == "blog_post":
            main_html = _extract_main_html_trafilatura(raw_html, page_url=normalized_canonical)
            if not main_html:
                main_html = _extract_general_html_bs4(raw_html, include_sections=False)
        else:
            bs4_html = _extract_general_html_bs4(raw_html, include_sections=True)
            trafilatura_html = _extract_main_html_trafilatura(
                raw_html, page_url=normalized_canonical
            )
            bs4_md = html_to_clean_markdown(bs4_html)
            traf_md = html_to_clean_markdown(trafilatura_html or "")
            main_html = bs4_html if len(bs4_md) >= len(traf_md) else trafilatura_html

        sanitized_original = sanitize_article_html(main_html or "")
        markdown = html_to_clean_markdown(main_html or "")

        if count_words(markdown) < 30 and candidate and candidate.raw_html:
            sanitized_original = sanitize_article_html(candidate.raw_html)
            markdown = html_to_clean_markdown(candidate.raw_html)

        title = (
            meta.title or (candidate.title if candidate else None) or normalized_canonical
        ).strip()[:500]
        meta_description = (
            meta.meta_description
            or meta.brand_description
            or (candidate.summary if candidate else None)
        )
        author = meta.author or (candidate.author if candidate else None)
        published_at = meta.published_at or (candidate.published_at if candidate else None)
        source_updated_at = meta.modified_at or (candidate.modified_at if candidate else None)
        language = (
            meta.language or (candidate.language if candidate else None) or default_language or "en"
        )

        # Retain lightweight summary for thin landing/index pages that only have metadata/navigation
        if not markdown.strip() and is_landing:
            summary_parts = [p for p in [title, meta.h1_text, meta_description] if p]
            markdown = "\n\n".join(summary_parts)

        categories = _merge_unique(meta.categories, candidate.categories if candidate else [])
        tags = _merge_unique(meta.tags, candidate.tags if candidate else [])
        featured_image_url = meta.featured_image_url or (
            candidate.featured_image_url if candidate else None
        )

        keywords = extract_keywords(
            markdown or title,
            title=title,
            language=language,
            max_keywords=self.settings.content_max_keywords,
        )
        optimized_context = build_optimized_context(
            title=f"[{content_type.upper()}] {title}",
            canonical_url=normalized_canonical,
            meta_description=meta_description,
            markdown_content=markdown,
            keywords=keywords,
            headings=meta.headings,
            published_at=published_at,
            language=language,
            max_chars=self.settings.content_max_context_chars,
        )

        structured_data: dict[str, Any] = {
            "content_type": content_type,
            "headings": meta.headings,
            "jsonld_types": meta.jsonld_types,
            "jsonld_objects": meta.jsonld_objects,
            "internal_links": meta.internal_links[:50],
            "external_links": meta.external_links[:30],
            "images": meta.images,
        }
        if content_type == "homepage":
            structured_data["brand_description"] = meta.brand_description or meta_description
            structured_data["navigation_links"] = meta.navigation_links
            structured_data["products_services"] = meta.products_services or meta.headings[:10]
        elif content_type in {"blog_index", "category", "tag", "archive"}:
            structured_data["discovered_links"] = meta.internal_links[:50]

        extracted_plain = markdown.strip() or (meta_description or "")

        return ExtractedContent(
            title=title,
            url=normalized_discovered,
            canonical_url=normalized_canonical,
            url_hash=hash_url(normalized_discovered),
            content_type=content_type,
            classification_method=classification_method,
            h1_text=meta.h1_text,
            author=author[:150] if author else None,
            meta_description=meta_description,
            original_content=sanitized_original,
            extracted_content=extracted_plain,
            markdown_content=markdown,
            optimized_context=optimized_context,
            keywords=keywords,
            categories=categories,
            tags=tags,
            language=language[:32] if language else None,
            content_hash=compute_content_hash(title, markdown),
            word_count=count_words(markdown),
            structured_data_json=structured_data,
            featured_image_url=featured_image_url,
            featured_image_alt=meta.featured_image_alt,
            published_at=published_at,
            source_updated_at=source_updated_at,
            headings=meta.headings,
        )

    def extract_from_markdown(
        self,
        raw_markdown: str,
        *,
        page_url: str,
        domain: str,
        candidate: DiscoveredCandidate | None = None,
        url_rules: list[WebsiteUrlRule] | None = None,
        manual_override_type: str | None = None,
        default_language: str | None = None,
    ) -> ExtractedContent:
        normalized_url = normalize_url(page_url)
        markdown = normalize_markdown(raw_markdown)

        heading_title: str | None = None
        for line in markdown.splitlines():
            if line.startswith("# "):
                heading_title = line[2:].strip()
                break

        title = (
            (candidate.title if candidate else None) or heading_title or normalized_url
        ).strip()[:500]
        language = (candidate.language if candidate else None) or default_language or "en"
        decision = classify_url(
            normalized_url,
            domain=domain,
            custom_rules=url_rules,
            source_methods=candidate.discovery_sources if candidate else None,
            manual_override_type=manual_override_type,
        )
        keywords = extract_keywords(
            markdown,
            title=title,
            language=language,
            max_keywords=self.settings.content_max_keywords,
        )
        optimized_context = build_optimized_context(
            title=f"[{decision.content_type.upper()}] {title}",
            canonical_url=normalized_url,
            meta_description=candidate.summary if candidate else None,
            markdown_content=markdown,
            keywords=keywords,
            published_at=candidate.published_at if candidate else None,
            language=language,
            max_chars=self.settings.content_max_context_chars,
        )

        return ExtractedContent(
            title=title,
            url=normalized_url,
            canonical_url=normalized_url,
            url_hash=hash_url(normalized_url),
            content_type=decision.content_type,
            classification_method=decision.classification_method,
            h1_text=heading_title,
            author=candidate.author if candidate else None,
            meta_description=candidate.summary if candidate else None,
            original_content=markdown,
            extracted_content=markdown,
            markdown_content=markdown,
            optimized_context=optimized_context,
            keywords=keywords,
            categories=list(candidate.categories) if candidate else [],
            tags=list(candidate.tags) if candidate else [],
            language=language[:32],
            content_hash=compute_content_hash(title, markdown),
            word_count=count_words(markdown),
            featured_image_url=candidate.featured_image_url if candidate else None,
            published_at=candidate.published_at if candidate else None,
            source_updated_at=candidate.modified_at if candidate else None,
        )


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in [*first, *second]:
        clean = item.strip()
        lowered = clean.lower()
        if clean and lowered not in seen:
            seen.add(lowered)
            result.append(clean)
    return result
