from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.models.website_url_rule import WebsiteUrlRule
from app.services.scanner.url_normalizer import is_same_site, normalize_url

CONTENT_TYPES: tuple[str, ...] = (
    "homepage",
    "page",
    "blog_index",
    "blog_post",
    "category",
    "tag",
    "archive",
    "custom",
)

RULE_TARGET_TYPES: tuple[str, ...] = (*CONTENT_TYPES, "exclude")

# System / binary URLs always excluded unless explicitly needed. Notice homepage `/`,
# `/category/*`, `/tag/*`, and `/author/*` are NOT in here so they can be discovered and classified.
SYSTEM_EXCLUDED_PATTERNS: tuple[str, ...] = (
    "/wp-admin/*",
    "/wp-login*",
    "/wp-content/*",
    "/wp-includes/*",
    "/wp-json/*",
    "/feed*",
    "/login*",
    "/logout*",
    "/register*",
    "/cart*",
    "/checkout*",
    "/account*",
    "/search*",
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.ico",
    "*.pdf",
    "*.zip",
    "*.css",
    "*.js",
    "*.woff*",
)

BLOG_INDEX_ROOTS: frozenset[str] = frozenset(
    {"/blog", "/blogs", "/news", "/articles", "/posts", "/journal", "/insights"}
)
BLOG_POST_PREFIXES: tuple[str, ...] = (
    "/blog/",
    "/blogs/",
    "/news/",
    "/articles/",
    "/posts/",
    "/journal/",
    "/insights/",
)
BLOG_INDEX_PAGE_RE = re.compile(
    r"^/(?:blog|blogs|news|articles|posts|journal|insights)/page/\d+/?$"
)
DATE_POST_RE = re.compile(r"^/(?:19|20)\d{2}/(?:0[1-9]|1[0-2])/(?:[0-3]\d/)?[a-z0-9\-_%]+$")
DATE_ARCHIVE_RE = re.compile(r"^/(?:19|20)\d{2}(?:/(?:0[1-9]|1[0-2]))?/?$")
PAGINATION_SUFFIX_RE = re.compile(r"(?:^|/)page/\d+/?$")

ARTICLE_JSONLD_TYPES: frozenset[str] = frozenset(
    {"article", "blogposting", "newsarticle", "techarticle", "report"}
)


@dataclass(frozen=True)
class ClassificationDecision:
    content_type: str
    classification_method: (
        str  # manual | root | custom_rule | default_rule | json_ld | source_evidence
    )
    is_excluded: bool = False
    exclusion_reason: str | None = None


def rule_matches_path(
    pattern: str, path: str, query: str = "", *, match_mode: str = "glob"
) -> bool:
    """Match a rule against a normalized path without conflating `/blog` with `/blog/*`."""
    pat = pattern.strip().lower()
    if not pat:
        return False
    norm_path = path.lower() or "/"
    if norm_path != "/":
        norm_path = norm_path.rstrip("/")
    full = f"{norm_path}?{query.lower()}" if query else norm_path

    mode = (match_mode or "glob").strip().lower()
    if mode == "exact":
        norm_pat = pat if pat == "/" else pat.rstrip("/")
        return norm_path == norm_pat or full == norm_pat
    if mode == "prefix":
        norm_pat = pat if pat == "/" else (pat.rstrip("*").rstrip("/") or "/")
        return (
            norm_path == norm_pat
            or norm_path.startswith(f"{norm_pat}/")
            or full.startswith(norm_pat)
        )

    # Strict glob: `/blog/*` matches children like `/blog/post-1`, NOT the index `/blog`.
    if pat != "/" and pat.endswith("/") and not pat.endswith("/*/"):
        pat = pat.rstrip("/")
    return fnmatch.fnmatch(norm_path, pat) or fnmatch.fnmatch(full, pat)


def _rule_specificity(rule: WebsiteUrlRule) -> tuple[int, int, int, int, int, int]:
    pat = rule.pattern.strip().lower()
    exact_bonus = 1 if rule.match_mode == "exact" or "*" not in pat else 0
    # Taxonomy patterns explicitly targeting category/tag/author rank above generic wildcards.
    taxonomy_bonus = (
        1
        if any(seg in pat for seg in ("/category", "/categories", "/tag", "/tags", "/author"))
        else 0
    )
    literal_segments = sum(1 for seg in pat.strip("/").split("/") if seg and "*" not in seg)
    literal_chars = len(pat.replace("*", "").replace("?", "").strip("/"))
    wildcard_count = pat.count("*") + pat.count("?")
    return (
        int(rule.priority),
        taxonomy_bonus,
        exact_bonus,
        literal_segments,
        literal_chars,
        -wildcard_count,
    )


def _classify_taxonomy_or_archive(path: str) -> str | None:
    lowered = path.lower()
    segments = [seg for seg in lowered.strip("/").split("/") if seg]
    if not segments:
        return None
    if any(seg in {"category", "categories"} for seg in segments):
        return "category"
    if any(seg in {"tag", "tags"} for seg in segments):
        return "tag"
    if any(seg in {"author", "authors", "archive", "archives"} for seg in segments):
        return "archive"
    if DATE_ARCHIVE_RE.match(lowered) or PAGINATION_SUFFIX_RE.search(lowered):
        # Differentiate paginated blog root (`/blog/page/2`) vs date/archive listings.
        if BLOG_INDEX_PAGE_RE.match(lowered):
            return "blog_index"
        return "archive"
    return None


def classify_url(
    raw_url: str,
    *,
    domain: str,
    custom_rules: list[WebsiteUrlRule] | None = None,
    excluded_patterns: list[str] | None = None,
    include_patterns: list[str] | None = None,
    jsonld_types: list[str] | None = None,
    og_type: str | None = None,
    source_methods: list[str] | None = None,
    manual_override_type: str | None = None,
) -> ClassificationDecision:
    """Deterministic URL classification with custom rules, specificity, and schema evidence."""
    try:
        normalized = normalize_url(raw_url, base_url=f"https://{domain}")
    except ValueError:
        return ClassificationDecision(
            "custom", "default_rule", is_excluded=True, exclusion_reason="invalid_url"
        )

    if not is_same_site(normalized, domain):
        return ClassificationDecision(
            "custom", "default_rule", is_excluded=True, exclusion_reason="cross_domain"
        )

    parsed = urlparse(normalized)
    path = parsed.path or "/"
    query = parsed.query or ""

    # System binary / admin exclusions (never excludes homepage `/`, category, tag, or author)
    for sys_pat in SYSTEM_EXCLUDED_PATTERNS:
        if rule_matches_path(sys_pat, path, query, match_mode="glob"):
            return ClassificationDecision(
                "custom", "default_rule", is_excluded=True, exclusion_reason="excluded_pattern"
            )

    # Configured website exclude patterns
    for exc_pat in excluded_patterns or []:
        if exc_pat.strip() and rule_matches_path(exc_pat, path, query, match_mode="glob"):
            return ClassificationDecision(
                "custom", "custom_rule", is_excluded=True, exclusion_reason="excluded_pattern"
            )

    # Manual classification override is preserved on rescans.
    if manual_override_type and manual_override_type in CONTENT_TYPES:
        return ClassificationDecision(manual_override_type, "manual", is_excluded=False)

    # Check enabled website_url_rules sorted by specificity + priority.
    enabled_rules = [r for r in (custom_rules or []) if r.is_enabled]
    enabled_rules.sort(key=_rule_specificity, reverse=True)

    # Root homepage check (only overridden if an explicit root exclude rule exists)
    if path == "/":
        for rule in enabled_rules:
            if rule.target_content_type == "exclude" and rule_matches_path(
                rule.pattern, "/", query, match_mode=rule.match_mode
            ):
                return ClassificationDecision(
                    "homepage", "custom_rule", is_excluded=True, exclusion_reason="excluded_pattern"
                )
        return ClassificationDecision("homepage", "root", is_excluded=False)

    # Taxonomy/archive detection (evaluated BEFORE broad wildcards like `/blog/*` unless
    # a higher-specificity taxonomy/exact custom rule matched).
    built_in_tax = _classify_taxonomy_or_archive(path)

    for rule in enabled_rules:
        if not rule_matches_path(rule.pattern, path, query, match_mode=rule.match_mode):
            continue
        target = rule.target_content_type.strip().lower()
        if target == "exclude":
            return ClassificationDecision(
                "custom", "custom_rule", is_excluded=True, exclusion_reason="excluded_pattern"
            )
        if target not in CONTENT_TYPES:
            continue
        # Preserve taxonomy/archive accuracy when a broad blog wildcard (e.g. `/blog/*`)
        # matches `/blog/category/sports/`, unless the custom rule explicitly mentions taxonomy
        # or explicitly overrides at priority > 100.
        if (
            built_in_tax is not None
            and target == "blog_post"
            and rule.priority <= 100
            and not any(
                seg in rule.pattern.lower()
                for seg in ("/category", "/categories", "/tag", "/tags", "/author", "/archive")
            )
        ):
            return ClassificationDecision(built_in_tax, "default_rule", is_excluded=False)
        return ClassificationDecision(target, "custom_rule", is_excluded=False)

    # Optional legacy include_patterns filter when explicitly set (root '/' handled above)
    includes = [p.strip() for p in (include_patterns or []) if p.strip()]
    if includes and not any(
        rule_matches_path(pat, path, query, match_mode="glob") for pat in includes
    ):
        return ClassificationDecision(
            "page", "default_rule", is_excluded=True, exclusion_reason="excluded_pattern"
        )

    if built_in_tax is not None:
        return ClassificationDecision(built_in_tax, "default_rule", is_excluded=False)

    lowered = path.lower()
    if lowered in BLOG_INDEX_ROOTS:
        return ClassificationDecision("blog_index", "default_rule", is_excluded=False)

    if any(
        lowered.startswith(prefix) and len(lowered) > len(prefix) for prefix in BLOG_POST_PREFIXES
    ):
        return ClassificationDecision("blog_post", "default_rule", is_excluded=False)

    if DATE_POST_RE.match(lowered):
        return ClassificationDecision("blog_post", "default_rule", is_excluded=False)

    # Use JSON-LD / OG metadata when URL structure does not indicate blog vs regular page.
    norm_jsonld = {str(t).strip().lower() for t in (jsonld_types or []) if t}
    if norm_jsonld & ARTICLE_JSONLD_TYPES or (og_type or "").strip().lower() == "article":
        return ClassificationDecision("blog_post", "json_ld", is_excluded=False)

    # WordPress REST `/wp-json/wp/v2/posts` or RSS-only items (when single-segment root slug)
    if source_methods:
        methods = {m.lower() for m in source_methods}
        if (
            ("wordpress" in methods or "wordpress_api" in methods or "rss" in methods)
            and "html" not in methods
            and "sitemap" not in methods
            and "homepage" not in methods
        ):
            return ClassificationDecision("blog_post", "source_evidence", is_excluded=False)

    return ClassificationDecision("page", "default_rule", is_excluded=False)


def serialize_classification_summary(counts: dict[str, Any]) -> dict[str, int]:
    return {
        "homepage": int(counts.get("homepage", 0)),
        "page": int(counts.get("page", 0)),
        "blog_index": int(counts.get("blog_index", 0)),
        "blog_post": int(counts.get("blog_post", 0)),
        "category": int(counts.get("category", 0)),
        "tag": int(counts.get("tag", 0)),
        "archive": int(counts.get("archive", 0)),
        "custom": int(counts.get("custom", 0)),
    }
