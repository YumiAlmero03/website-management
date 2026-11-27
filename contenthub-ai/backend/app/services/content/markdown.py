from __future__ import annotations

import re

from bs4 import BeautifulSoup
from markdownify import markdownify as to_markdown

BOILERPLATE_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "nav",
    "footer",
    "aside",
    "svg",
    "canvas",
)

BOILERPLATE_CLASS_HINTS: tuple[str, ...] = (
    "cookie",
    "consent",
    "popup",
    "modal",
    "newsletter",
    "subscribe",
    "related-posts",
    "related-articles",
    "share-buttons",
    "social-share",
    "advertisement",
    "ad-slot",
    "promo-banner",
    "breadcrumb",
    "sidebar",
)

ALLOWED_HTML_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "strong",
        "b",
        "em",
        "i",
        "a",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
        "figure",
        "figcaption",
    }
)


def sanitize_article_html(raw_html: str) -> str:
    """Strip unsafe scripts, events, and boilerplate from untrusted article HTML."""
    if not raw_html or not raw_html.strip():
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.find_all(list(BOILERPLATE_TAGS)):
        tag.decompose()

    # Remove obvious boilerplate widgets by class/id hints.
    for el in list(soup.find_all(True)):
        if el.attrs is None:
            continue
        classes = " ".join(el.get("class") or [])
        el_id = str(el.get("id") or "")
        combined = f"{classes} {el_id}".lower()
        if any(hint in combined for hint in BOILERPLATE_CLASS_HINTS):
            el.decompose()

    # Strip unsafe attributes (on* handlers, javascript: hrefs, style injection).
    for tag in list(soup.find_all(True)):
        if tag.name not in ALLOWED_HTML_TAGS:
            tag.unwrap()
            continue
        safe_attrs: dict[str, str] = {}
        if tag.name == "a":
            href = str(tag.get("href") or "").strip()
            if href.startswith(("http://", "https://", "/")):
                safe_attrs["href"] = href
                safe_attrs["rel"] = "noopener noreferrer nofollow"
        tag.attrs = safe_attrs

    return str(soup).strip()


def html_to_clean_markdown(raw_html: str) -> str:
    """Convert untrusted HTML into clean, normalized Markdown preserving structure and links."""
    sanitized = sanitize_article_html(raw_html)
    if not sanitized:
        return ""
    md = to_markdown(
        sanitized,
        heading_style="ATX",
        bullets="-",
        strip=["img"],
    )
    return normalize_markdown(md)


def normalize_markdown(markdown_text: str) -> str:
    if not markdown_text:
        return ""
    lines = [line.rstrip() for line in markdown_text.replace("\r\n", "\n").splitlines()]
    collapsed = "\n".join(lines)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    return collapsed.strip()


def count_words(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b[\w'-]+\b", text))
