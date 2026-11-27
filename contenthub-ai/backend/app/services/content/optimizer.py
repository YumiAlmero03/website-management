from __future__ import annotations

import re
from datetime import datetime

from rapidfuzz import fuzz

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"\'])")
_NUMBER_FACT_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")


def _extract_markdown_headings(markdown_content: str) -> list[str]:
    headings: list[str] = []
    for line in markdown_content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("# ", "## ", "### ")):
            heading = stripped.lstrip("#").strip()
            if heading and heading not in headings:
                headings.append(heading)
    return headings[:12]


def _extract_plain_paragraphs(markdown_content: str) -> list[str]:
    paragraphs: list[str] = []
    for block in re.split(r"\n{2,}", markdown_content):
        cleaned = block.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"[*_`>]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) >= 35:
            paragraphs.append(cleaned)
    return paragraphs


def _select_important_sentences(
    markdown_content: str,
    *,
    keywords: list[str],
    headings: list[str],
    char_budget: int,
) -> list[str]:
    paragraphs = _extract_plain_paragraphs(markdown_content)
    if not paragraphs:
        return []

    raw_sentences: list[tuple[int, str]] = []
    idx = 0
    for para in paragraphs:
        parts = _SENTENCE_SPLIT_RE.split(para) if len(para) > 180 else [para]
        for sentence in parts:
            clean_sent = sentence.strip()
            if len(clean_sent) < 25:
                continue
            raw_sentences.append((idx, clean_sent))
            idx += 1

    if not raw_sentences:
        return []

    keyword_terms = [kw.lower() for kw in keywords[:12]]
    heading_terms = {
        word.lower() for h in headings for word in re.findall(r"\b[A-Za-z0-9]{4,}\b", h)
    }

    scored: list[tuple[float, int, str]] = []
    total_sentences = len(raw_sentences)
    for pos, sentence in raw_sentences:
        lower = sentence.lower()
        score = 0.0
        # Lead sentences carry high summary value.
        if pos == 0:
            score += 3.0
        elif pos <= 2:
            score += 1.5
        elif pos == total_sentences - 1:
            score += 0.8

        # Keyword relevance.
        score += sum(1.5 for kw in keyword_terms if kw in lower)
        # Heading overlap.
        score += sum(0.6 for term in heading_terms if term in lower)
        # Concrete numbers/dates/percentages indicate factual density.
        if _NUMBER_FACT_RE.search(sentence):
            score += 1.2
        # Prefer informative, non-bloated sentence lengths.
        if 60 <= len(sentence) <= 280:
            score += 0.7

        scored.append((score, pos, sentence))

    scored.sort(key=lambda item: (-item[0], item[1]))

    chosen: list[tuple[int, str]] = []
    used_chars = 0
    for _score, pos, sentence in scored:
        if any(fuzz.ratio(sentence, existing) >= 82 for _, existing in chosen):
            continue
        projected = used_chars + len(sentence) + 4
        if projected > char_budget and chosen:
            continue
        chosen.append((pos, sentence))
        used_chars = projected
        if used_chars >= char_budget:
            break

    # Restore original reading order.
    chosen.sort(key=lambda item: item[0])
    return [sentence for _, sentence in chosen]


def build_optimized_context(
    *,
    title: str,
    canonical_url: str,
    meta_description: str | None,
    markdown_content: str,
    keywords: list[str],
    headings: list[str] | None = None,
    published_at: datetime | None = None,
    language: str | None = None,
    max_chars: int = 4000,
) -> str:
    """Build compact factual Markdown context natively in Python for Phase 3 Gemini prompts."""
    resolved_headings = headings if headings else _extract_markdown_headings(markdown_content)

    header_lines: list[str] = [
        f"Title: {title.strip()}",
        f"Canonical URL: {canonical_url.strip()}",
    ]
    if language:
        header_lines.append(f"Language: {language.strip()}")
    if published_at:
        header_lines.append(f"Published: {published_at.strftime('%Y-%m-%d')}")
    if meta_description:
        header_lines.append(f"Meta Description: {meta_description.strip()[:320]}")
    if keywords:
        header_lines.append(f"Keywords: {', '.join(keywords[:12])}")
    if resolved_headings:
        header_lines.append("Key Headings:")
        for heading in resolved_headings[:8]:
            header_lines.append(f"- {heading}")

    header_block = "\n".join(header_lines)
    remaining_budget = max(400, max_chars - len(header_block) - 40)

    selected_sentences = _select_important_sentences(
        markdown_content,
        keywords=keywords,
        headings=resolved_headings,
        char_budget=remaining_budget,
    )

    sections = [header_block]
    if selected_sentences:
        key_points = "\n".join(f"- {sentence}" for sentence in selected_sentences)
        sections.append(f"Key Facts & Extracts:\n{key_points}")

    combined = "\n\n".join(sections).strip()
    if len(combined) > max_chars:
        combined = combined[: max_chars - 3].rstrip() + "..."
    return combined
