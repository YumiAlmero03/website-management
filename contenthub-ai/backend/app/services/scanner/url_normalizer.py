from __future__ import annotations

import fnmatch
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

TRACKING_QUERY_PREFIXES: tuple[str, ...] = ("utm_", "hsa_", "pk_", "mtm_")
TRACKING_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        "fbclid",
        "gclid",
        "gbraid",
        "wbraid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "yclid",
        "ref",
        "ref_src",
        "ref_url",
        "_hsenc",
        "_hsmi",
        "mkt_tok",
        "s_cid",
        "spm",
    }
)

# System binary/admin URLs excluded by default; homepage `/`, `/category/*`, `/tag/*`,
# and `/author/*` are NOT excluded so they can be discovered and classified properly.
DEFAULT_EXCLUDED_PATTERNS: tuple[str, ...] = (
    "/wp-admin/*",
    "/wp-login*",
    "/wp-content/*",
    "/wp-includes/*",
    "/wp-json/*",
    "/search*",
    "/login*",
    "/logout*",
    "/register*",
    "/cart*",
    "/checkout*",
    "/account*",
    "/feed*",
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

_SAFE_PATTERN_REGEX = re.compile(r"^[A-Za-z0-9/_\-.*?=]+$")


def normalize_domain(raw_domain: str) -> str:
    cleaned = raw_domain.strip().lower()
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        cleaned = (parsed.hostname or "").lower()
    else:
        cleaned = cleaned.split("/", 1)[0].split(":", 1)[0]
    cleaned = cleaned.rstrip(".")
    if not cleaned or " " in cleaned or "." not in cleaned:
        raise ValueError("Please provide a valid website domain (e.g., example.com).")
    return cleaned


def normalize_url(raw_url: str, *, base_url: str | None = None) -> str:
    """Normalize a URL while preserving meaningful content query parameters."""
    candidate = raw_url.strip()
    if base_url:
        candidate = urljoin(base_url, candidate)

    parsed = urlparse(candidate)
    scheme = (parsed.scheme or "https").lower()
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise ValueError(f"Cannot normalize URL without hostname: {raw_url!r}")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid port in URL: {raw_url!r}") from exc

    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443) or port is None:
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    raw_path = parsed.path or "/"
    collapsed_path = re.sub(r"/{2,}", "/", raw_path)
    if collapsed_path != "/" and collapsed_path.endswith("/"):
        collapsed_path = collapsed_path.rstrip("/")

    kept_params: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_PARAMS or any(
            lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES
        ):
            continue
        kept_params.append((key, value))
    kept_params.sort(key=lambda pair: (pair[0], pair[1]))
    normalized_query = urlencode(kept_params, doseq=True)

    return urlunparse((scheme, netloc, collapsed_path, "", normalized_query, ""))


def hash_url(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


def is_same_site(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").strip().lower().rstrip(".")
    target = domain.strip().lower().rstrip(".")
    bare_target = target[4:] if target.startswith("www.") else target
    bare_host = host[4:] if host.startswith("www.") else host
    return bare_host == bare_target or bare_host.endswith(f".{bare_target}")


def validate_url_patterns(patterns: list[str] | None) -> list[str]:
    if not patterns:
        return []
    cleaned: list[str] = []
    for raw in patterns:
        pattern = raw.strip()
        if not pattern:
            continue
        if len(pattern) > 200 or not _SAFE_PATTERN_REGEX.match(pattern):
            raise ValueError(
                f"Invalid URL pattern '{pattern}'. "
                "Use safe glob patterns such as '/blog/*' or '/tag/*'."
            )
        if pattern not in cleaned:
            cleaned.append(pattern)
    return cleaned


def matches_url_patterns(
    url: str,
    *,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    apply_default_excludes: bool = True,
) -> bool:
    """Evaluate safe glob include/exclude rules against a URL path and query (homepage allowed)."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    path_with_query = f"{path}?{parsed.query}" if parsed.query else path

    all_excludes = list(exclude_patterns or [])
    if apply_default_excludes:
        all_excludes.extend(DEFAULT_EXCLUDED_PATTERNS)

    for pattern in all_excludes:
        if _glob_match(pattern, path, path_with_query):
            return False

    includes = [p.strip() for p in (include_patterns or []) if p.strip()]
    if not includes or path == "/":
        return True

    return any(_glob_match(pattern, path, path_with_query) for pattern in includes)


def _glob_match(pattern: str, path: str, path_with_query: str) -> bool:
    lower_pat = (
        pattern.lower().rstrip("/")
        if pattern != "/" and not pattern.endswith("/*/")
        else pattern.lower()
    )
    lower_path = path.lower().rstrip("/") if path != "/" else "/"
    lower_full = path_with_query.lower()
    return bool(fnmatch.fnmatch(lower_path, lower_pat) or fnmatch.fnmatch(lower_full, lower_pat))
