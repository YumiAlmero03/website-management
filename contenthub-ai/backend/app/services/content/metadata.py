from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ARTICLE_SCHEMA_TYPES: frozenset[str] = frozenset(
    {"article", "blogposting", "newsarticle", "techarticle", "webpage", "report"}
)


@dataclass
class ExtractedMetadata:
    title: str | None = None
    canonical_url: str | None = None
    meta_description: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    modified_at: datetime | None = None
    featured_image_url: str | None = None
    featured_image_alt: str | None = None
    language: str | None = None
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)


def _parse_datetime(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        try:
            dt = datetime.strptime(cleaned[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=UTC)
        except ValueError:
            return None


def _meta_content(
    soup: BeautifulSoup, *, name: str | None = None, prop: str | None = None
) -> str | None:
    attrs: dict[str, str] = {}
    if name:
        attrs["name"] = name
    if prop:
        attrs["property"] = prop
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        value = str(tag["content"]).strip()
        if value:
            return value
    return None


def _iter_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                nodes.extend(n for n in item["@graph"] if isinstance(n, dict))
            else:
                nodes.append(item)
    return nodes


def _extract_jsonld_author(raw_author: Any) -> str | None:
    if isinstance(raw_author, str) and raw_author.strip():
        return raw_author.strip()
    if isinstance(raw_author, dict) and isinstance(raw_author.get("name"), str):
        return raw_author["name"].strip() or None
    if isinstance(raw_author, list) and raw_author:
        return _extract_jsonld_author(raw_author[0])
    return None


def _extract_jsonld_image(raw_image: Any) -> str | None:
    if isinstance(raw_image, str) and raw_image.strip():
        return raw_image.strip()
    if isinstance(raw_image, dict):
        for key in ("url", "contentUrl"):
            val = raw_image.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    if isinstance(raw_image, list) and raw_image:
        return _extract_jsonld_image(raw_image[0])
    return None


def extract_html_metadata(html_content: str, *, page_url: str) -> ExtractedMetadata:
    """Extract canonical URL, OG/Twitter/JSON-LD metadata, headings, and featured image."""
    soup = BeautifulSoup(html_content, "html.parser")
    meta = ExtractedMetadata()

    # Language
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        meta.language = str(html_tag["lang"]).strip()[:32]
    elif og_locale := _meta_content(soup, prop="og:locale"):
        meta.language = og_locale.replace("_", "-")[:32]

    # Canonical URL
    canonical_link = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
    if canonical_link and canonical_link.get("href"):
        meta.canonical_url = urljoin(page_url, str(canonical_link["href"]).strip())

    # Title priority: og:title -> h1 -> <title>
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else None
    doc_title = soup.title.string.strip() if soup.title and soup.title.string else None
    meta.title = _meta_content(soup, prop="og:title") or h1_text or doc_title

    # Description priority: meta description -> og:description -> twitter:description
    meta.meta_description = (
        _meta_content(soup, name="description")
        or _meta_content(soup, prop="og:description")
        or _meta_content(soup, name="twitter:description")
    )

    meta.author = _meta_content(soup, name="author") or _meta_content(soup, prop="article:author")
    meta.published_at = _parse_datetime(
        _meta_content(soup, prop="article:published_time")
        or _meta_content(soup, name="pubdate")
        or _meta_content(soup, name="publish-date")
    )
    meta.modified_at = _parse_datetime(
        _meta_content(soup, prop="article:modified_time")
        or _meta_content(soup, prop="og:updated_time")
    )

    # Categories & tags from Open Graph / meta keywords
    section = _meta_content(soup, prop="article:section")
    if section:
        meta.categories.append(section)
    for tag_meta in soup.find_all("meta", attrs={"property": "article:tag"}):
        val = str(tag_meta.get("content") or "").strip()
        if val and val not in meta.tags:
            meta.tags.append(val)

    # Featured image priority: og:image -> twitter:image -> JSON-LD -> first article <img>
    raw_image = (
        _meta_content(soup, prop="og:image")
        or _meta_content(soup, prop="og:image:secure_url")
        or _meta_content(soup, name="twitter:image")
    )
    meta.featured_image_alt = _meta_content(soup, prop="og:image:alt") or _meta_content(
        soup, name="twitter:image:alt"
    )

    # Enrich from JSON-LD structured data
    for node in _iter_jsonld(soup):
        raw_type = node.get("@type")
        type_list = raw_type if isinstance(raw_type, list) else [raw_type]
        normalized_types = {str(t).lower() for t in type_list if t}
        if not (normalized_types & ARTICLE_SCHEMA_TYPES):
            continue

        if not meta.title and isinstance(node.get("headline"), str):
            meta.title = node["headline"].strip()
        if not meta.meta_description and isinstance(node.get("description"), str):
            meta.meta_description = node["description"].strip()
        if not meta.author:
            meta.author = _extract_jsonld_author(node.get("author"))
        if not meta.published_at:
            meta.published_at = _parse_datetime(node.get("datePublished"))
        if not meta.modified_at:
            meta.modified_at = _parse_datetime(node.get("dateModified"))
        if not raw_image:
            raw_image = _extract_jsonld_image(node.get("image"))
        if not meta.language and isinstance(node.get("inLanguage"), str):
            meta.language = node["inLanguage"].strip()[:32]
        if isinstance(node.get("articleSection"), str):
            sec = node["articleSection"].strip()
            if sec and sec not in meta.categories:
                meta.categories.append(sec)
        break

    # Fallback: first meaningful image inside <article> or <main>
    if not raw_image:
        container = soup.find("article") or soup.find("main") or soup
        for img in container.find_all("img", src=True):
            src = str(img.get("src") or "").strip()
            if not src or src.startswith("data:") or src.lower().endswith(".svg"):
                continue
            raw_image = src
            if not meta.featured_image_alt and img.get("alt"):
                meta.featured_image_alt = str(img["alt"]).strip()[:255]
            break

    if raw_image:
        meta.featured_image_url = urljoin(page_url, raw_image)

    # Collect headings (h1-h3) from article/main body
    body_scope = soup.find("article") or soup.find("main") or soup.body or soup
    for heading in body_scope.find_all(["h1", "h2", "h3"]):
        text = heading.get_text(" ", strip=True)
        if text and len(text) <= 240 and text not in meta.headings:
            meta.headings.append(text)
        if len(meta.headings) >= 20:
            break

    return meta
