from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from rapidfuzz import fuzz

from app.models.website_content import WebsiteContent


def compute_content_hash(title: str, markdown_content: str) -> str:
    """Compute a deterministic SHA-256 hash over normalized content title and Markdown body."""
    normalized_title = re.sub(r"\s+", " ", (title or "").strip().lower())
    normalized_body = re.sub(r"\s+", " ", (markdown_content or "").strip().lower())
    payload = f"{normalized_title}\n{normalized_body}".encode()
    return hashlib.sha256(payload).hexdigest()


def find_near_duplicate(
    *,
    title: str,
    markdown_content: str,
    existing_contents: Iterable[WebsiteContent],
    exclude_content_id: int | None = None,
    threshold: float = 88.0,
) -> tuple[int, float] | None:
    """Optional RapidFuzz near-duplicate detector (advisory only; never auto-merges or deletes)."""
    sample = f"{title}\n{(markdown_content or '')[:2000]}".strip().lower()
    if len(sample) < 40:
        return None

    best_match_id: int | None = None
    best_score = 0.0

    for item in existing_contents:
        if exclude_content_id is not None and item.id == exclude_content_id:
            continue
        other = f"{item.title}\n{(item.markdown_content or '')[:2000]}".strip().lower()
        if len(other) < 40:
            continue
        score = float(fuzz.token_set_ratio(sample, other))
        if score >= threshold and score > best_score:
            best_score = score
            best_match_id = item.id

    if best_match_id is None:
        return None
    return best_match_id, round(best_score, 2)
