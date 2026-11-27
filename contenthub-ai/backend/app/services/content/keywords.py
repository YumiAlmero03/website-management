from __future__ import annotations

import re
from collections import Counter

import yake

_SUPPORTED_YAKE_LANGS: frozenset[str] = frozenset(
    {"en", "pt", "es", "fr", "de", "it", "nl", "id", "ms", "tr", "vi", "tl"}
)

_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "with",
        "this",
        "from",
        "your",
        "have",
        "will",
        "into",
        "about",
        "more",
        "when",
        "what",
        "which",
        "their",
        "there",
        "also",
        "been",
        "were",
        "they",
        "them",
        "than",
        "then",
        "just",
        "only",
        "over",
        "such",
        "some",
        "most",
        "very",
        "can",
        "are",
        "was",
        "has",
        "had",
        "not",
        "but",
        "you",
        "our",
        "all",
        "how",
        "why",
        "ang",
        "mga",
        "para",
        "nang",
        "kung",
        "hindi",
    }
)


def _normalize_lang(language: str | None) -> str:
    if not language:
        return "en"
    code = language.strip().lower().split("-", 1)[0].split("_", 1)[0]
    if code in {"fil", "taglish"}:
        return "en"
    return code if code in _SUPPORTED_YAKE_LANGS else "en"


def extract_keywords(
    text: str,
    *,
    title: str | None = None,
    language: str | None = None,
    max_keywords: int = 12,
) -> list[str]:
    """Extract key phrases natively in Python via YAKE without invoking any AI provider."""
    combined = f"{title or ''}\n\n{text or ''}".strip()
    if not combined:
        return []

    plain = re.sub(r"[#*_`>\[\]()]+", " ", combined)
    plain = re.sub(r"https?://\S+", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) < 20:
        return _fallback_keywords(plain, max_keywords=max_keywords)

    lang = _normalize_lang(language)
    try:
        extractor = yake.KeywordExtractor(
            lan=lang,
            n=3,
            dedupLim=0.7,
            dedupFunc="seqm",
            windowsSize=1,
            top=max_keywords * 2,
        )
        raw_pairs = extractor.extract_keywords(plain[:25000])
        keywords: list[str] = []
        seen: set[str] = set()
        for phrase, _score in raw_pairs:
            cleaned = re.sub(r"\s+", " ", phrase).strip(" .,:;-_\"'")
            lowered = cleaned.lower()
            if len(cleaned) < 3 or lowered in seen or lowered in _STOPWORDS:
                continue
            seen.add(lowered)
            keywords.append(cleaned)
            if len(keywords) >= max_keywords:
                break
        if keywords:
            return keywords
    except Exception:
        pass

    return _fallback_keywords(plain, max_keywords=max_keywords)


def _fallback_keywords(text: str, *, max_keywords: int) -> list[str]:
    tokens = [
        tok.lower()
        for tok in re.findall(r"\b[A-Za-z][A-Za-z0-9\-]{2,}\b", text)
        if tok.lower() not in _STOPWORDS
    ]
    counts = Counter(tokens)
    return [word for word, _count in counts.most_common(max_keywords)]
