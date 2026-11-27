from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.services.scanner.url_normalizer import is_same_site, normalize_url

ARTICLE_SCHEMA_TYPES: frozenset[str] = frozenset(
    {
        "article",
        "blogposting",
        "newsarticle",
        "techarticle",
        "webpage",
        "report",
        "product",
        "service",
    }
)


@dataclass
class ExtractedMetadata:
    title: str | None = None
    canonical_url: str | None = None
    meta_description: str | None = None
    h1_text: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    modified_at: datetime | None = None
    featured_image_url: str | None = None
    featured_image_alt: str | None = None
    language: str | None = None
    og_type: str | None = None
    brand_description: str | None = None
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    jsonld_types: list[str] = field(default_factory=list)
    jsonld_objects: list[dict[str, Any]] = field(default_factory=list)
    navigation_links: list[dict[str, str]] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    products_services: list[str] = field(default_factory=list)


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


def extract_html_metadata(
    html_content: str, *, page_url: str, domain: str | None = None
) -> ExtractedMetadata:
    """Extract canonical URL, H1, OG/Twitter/JSON-LD metadata, nav/internal links, and images."""
    soup = BeautifulSoup(html_content, "html.parser")
    meta = ExtractedMetadata()
    resolved_domain = domain or (urlparse(page_url).hostname or "")

    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        meta.language = str(html_tag["lang"]).strip()[:32]
    elif og_locale := _meta_content(soup, prop="og:locale"):
        meta.language = og_locale.replace("_", "-")[:32]

    canonical_link = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
    if canonical_link and canonical_link.get("href"):
        meta.canonical_url = urljoin(page_url, str(canonical_link["href"]).strip())

    h1 = soup.find("h1")
    meta.h1_text = h1.get_text(" ", strip=True)[:500] if h1 else None
    doc_title = soup.title.string.strip() if soup.title and soup.title.string else None
    meta.title = _meta_content(soup, prop="og:title") or meta.h1_text or doc_title
    meta.og_type = _meta_content(soup, prop="og:type")

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

    section = _meta_content(soup, prop="article:section")
    if section:
        meta.categories.append(section)
    for tag_meta in soup.find_all("meta", attrs={"property": "article:tag"}):
        val = str(tag_meta.get("content") or "").strip()
        if val and val not in meta.tags:
            meta.tags.append(val)

    raw_image = (
        _meta_content(soup, prop="og:image")
        or _meta_content(soup, prop="og:image:secure_url")
        or _meta_content(soup, name="twitter:image")
    )
    meta.featured_image_alt = _meta_content(soup, prop="og:image:alt") or _meta_content(
        soup, name="twitter:image:alt"
    )

    for node in _iter_jsonld(soup):
        raw_type = node.get("@type")
        type_list = raw_type if isinstance(raw_type, list) else [raw_type]
        for t in type_list:
            if t and str(t).strip() not in meta.jsonld_types:
                meta.jsonld_types.append(str(t).strip())
        normalized_types = {str(t).lower() for t in type_list if t}

        if len(meta.jsonld_objects) < 8:
            meta.jsonld_objects.append(
                {
                    k: v
                    for k, v in node.items()
                    if k in {"@type", "name", "headline", "url", "description"}
                }
            )

        if "organization" in normalized_types or "website" in normalized_types:
            desc = node.get("description")
            if isinstance(desc, str) and desc.strip() and not meta.brand_description:
                meta.brand_description = desc.strip()

        if "product" in normalized_types or "service" in normalized_types:
            pname = node.get("name")
            if (
                isinstance(pname, str)
                and pname.strip()
                and pname.strip() not in meta.products_services
            ):
                meta.products_services.append(pname.strip())

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

    # Collect navigation links, internal links, and external links
    nav_seen: set[str] = set()
    for nav_el in soup.select("nav a[href], header a[href]"):
        href = str(nav_el.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            norm = normalize_url(href, base_url=page_url)
        except ValueError:
            continue
        if norm not in nav_seen and is_same_site(norm, resolved_domain):
            nav_seen.add(norm)
            meta.navigation_links.append(
                {"label": nav_el.get_text(" ", strip=True)[:80] or norm, "url": norm}
            )
        if len(meta.navigation_links) >= 30:
            break

    int_seen: set[str] = set()
    ext_seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            norm = normalize_url(href, base_url=page_url)
        except ValueError:
            continue
        if is_same_site(norm, resolved_domain):
            if norm not in int_seen and len(meta.internal_links) < 100:
                int_seen.add(norm)
                meta.internal_links.append(norm)
        elif (
            norm.startswith(("http://", "https://"))
            and norm not in ext_seen
            and len(meta.external_links) < 50
        ):
            ext_seen.add(norm)
            meta.external_links.append(norm)

    # Collect main images
    img_seen: set[str] = set()
    img_scope = soup.find("article") or soup.find("main") or soup
    for img in img_scope.find_all("img", src=True):
        src = str(img.get("src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        abs_img = urljoin(page_url, src)
        if abs_img not in img_seen and len(meta.images) < 15:
            img_seen.add(abs_img)
            meta.images.append({"url": abs_img, "alt": str(img.get("alt") or "").strip()[:160]})
        if not raw_image and not src.lower().endswith(".svg"):
            raw_image = src
            if not meta.featured_image_alt and img.get("alt"):
                meta.featured_image_alt = str(img["alt"]).strip()[:255]

    if raw_image:
        meta.featured_image_url = urljoin(page_url, raw_image)

    body_scope = soup.find("article") or soup.find("main") or soup.body or soup
    for heading in body_scope.find_all(["h1", "h2", "h3"]):
        text = heading.get_text(" ", strip=True)
        if text and len(text) <= 240 and text not in meta.headings:
            meta.headings.append(text)
        if len(meta.headings) >= 25:
            break

    return meta
