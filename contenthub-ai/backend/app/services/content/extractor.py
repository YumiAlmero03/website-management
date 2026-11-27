from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import trafilatura
from bs4 import BeautifulSoup

from app.config import Settings
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
from app.services.scanner.url_normalizer import hash_url, is_same_site, normalize_url


@dataclass
class ExtractedArticle:
    title: str
    canonical_url: str
    url_hash: str
    author: str | None
    meta_description: str | None
    original_content: str
    markdown_content: str
    optimized_context: str
    keywords: list[str]
    categories: list[str]
    tags: list[str]
    language: str | None
    content_hash: str
    word_count: int
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


def _extract_main_html_bs4_fallback(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "footer", "aside", "noscript", "form"]):
        tag.decompose()

    target = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )
    return str(target)


class ContentExtractionEngine:
    """Extracts clean article content via Trafilatura + BeautifulSoup4 fallback without AI calls."""

    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings

    def extract_from_html(
        self,
        raw_html: str,
        *,
        page_url: str,
        domain: str,
        candidate: DiscoveredCandidate | None = None,
        default_language: str | None = None,
    ) -> ExtractedArticle:
        meta = extract_html_metadata(raw_html, page_url=page_url)

        # Validate canonical URL stays on the same site before overriding discovery URL.
        chosen_url = page_url
        if meta.canonical_url:
            try:
                norm_canonical = normalize_url(meta.canonical_url, base_url=page_url)
                if is_same_site(norm_canonical, domain):
                    chosen_url = norm_canonical
            except ValueError:
                pass
        normalized_canonical = normalize_url(chosen_url, base_url=page_url)

        main_html = _extract_main_html_trafilatura(raw_html, page_url=normalized_canonical)
        if not main_html:
            main_html = _extract_main_html_bs4_fallback(raw_html)

        sanitized_original = sanitize_article_html(main_html)
        markdown = html_to_clean_markdown(main_html)

        # If HTML extraction was sparse but candidate already carried rich HTML (e.g., WP REST API).
        if count_words(markdown) < 30 and candidate and candidate.raw_html:
            sanitized_original = sanitize_article_html(candidate.raw_html)
            markdown = html_to_clean_markdown(candidate.raw_html)

        title = (
            meta.title or (candidate.title if candidate else None) or normalized_canonical
        ).strip()[:500]
        meta_description = meta.meta_description or (candidate.summary if candidate else None)
        author = meta.author or (candidate.author if candidate else None)
        published_at = meta.published_at or (candidate.published_at if candidate else None)
        source_updated_at = meta.modified_at or (candidate.modified_at if candidate else None)
        language = (
            meta.language or (candidate.language if candidate else None) or default_language or "en"
        )

        categories = _merge_unique(meta.categories, candidate.categories if candidate else [])
        tags = _merge_unique(meta.tags, candidate.tags if candidate else [])
        featured_image_url = meta.featured_image_url or (
            candidate.featured_image_url if candidate else None
        )

        keywords = extract_keywords(
            markdown,
            title=title,
            language=language,
            max_keywords=self.settings.content_max_keywords,
        )
        optimized_context = build_optimized_context(
            title=title,
            canonical_url=normalized_canonical,
            meta_description=meta_description,
            markdown_content=markdown,
            keywords=keywords,
            headings=meta.headings,
            published_at=published_at,
            language=language,
            max_chars=self.settings.content_max_context_chars,
        )

        return ExtractedArticle(
            title=title,
            canonical_url=normalized_canonical,
            url_hash=hash_url(normalized_canonical),
            author=author[:150] if author else None,
            meta_description=meta_description,
            original_content=sanitized_original,
            markdown_content=markdown,
            optimized_context=optimized_context,
            keywords=keywords,
            categories=categories,
            tags=tags,
            language=language[:32] if language else None,
            content_hash=compute_content_hash(title, markdown),
            word_count=count_words(markdown),
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
        candidate: DiscoveredCandidate | None = None,
        default_language: str | None = None,
    ) -> ExtractedArticle:
        normalized_canonical = normalize_url(page_url)
        markdown = normalize_markdown(raw_markdown)

        heading_title: str | None = None
        for line in markdown.splitlines():
            if line.startswith("# "):
                heading_title = line[2:].strip()
                break

        title = (
            (candidate.title if candidate else None) or heading_title or normalized_canonical
        ).strip()[:500]
        language = (candidate.language if candidate else None) or default_language or "en"
        keywords = extract_keywords(
            markdown,
            title=title,
            language=language,
            max_keywords=self.settings.content_max_keywords,
        )
        optimized_context = build_optimized_context(
            title=title,
            canonical_url=normalized_canonical,
            meta_description=candidate.summary if candidate else None,
            markdown_content=markdown,
            keywords=keywords,
            published_at=candidate.published_at if candidate else None,
            language=language,
            max_chars=self.settings.content_max_context_chars,
        )

        return ExtractedArticle(
            title=title,
            canonical_url=normalized_canonical,
            url_hash=hash_url(normalized_canonical),
            author=candidate.author if candidate else None,
            meta_description=candidate.summary if candidate else None,
            original_content=markdown,
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
