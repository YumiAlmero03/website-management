from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.models.content_keyword import ContentKeyword
from app.models.website import Website
from app.models.website_content import WebsiteContent
from app.models.website_knowledge_profile import WebsiteKnowledgeProfile
from app.repositories.keyword_approval_repo import normalize_keyphrase
from app.schemas.keyword_approval import (
    CannibalizationMatchResponse,
    ImageAltSuggestionItem,
)

_SLUG_NOISE_TAILS: frozenset[str] = frozenset(
    {
        "whats",
        "what",
        "difference",
        "differences",
        "guide",
        "complete",
        "ultimate",
        "explained",
        "overview",
        "tutorial",
        "review",
        "reviews",
        "tips",
        "step",
        "html",
        "php",
        "aspx",
        "index",
    }
)
_SLUG_CONNECTOR_WORDS: frozenset[str] = frozenset(
    {"vs", "and", "or", "for", "to", "in", "on", "of", "the", "a"}
)
_QUESTION_SPLITS = re.compile(
    r"\s*(?::|—|\s+-\s+|\s+\|\s+|\bwhat(?:'s|s|\s+is)\b|\bhow\s+to\b|\bwhy\s+you\b|\?)",
    flags=re.IGNORECASE,
)
_FILE_EXT_RE = re.compile(r"\.[a-z0-9]{2,5}$", flags=re.IGNORECASE)


@dataclass(frozen=True)
class SuggestedKeywordsResult:
    focus_keyphrase: str
    secondary_keywords: list[str]
    anchor_text_variations: list[str]
    image_alt_suggestions: list[dict[str, Any]]
    suggestion_source: str = "python_auto"
    keyword_generation_method: str = "python"
    keyword_generation_status: str = "generated"
    keyword_evidence: list[dict[str, Any]] | None = None
    keyword_scores: dict[str, Any] | None = None
    keyword_model: str | None = None
    keyword_input_hash: str | None = None
    game_name: str | None = None
    provider_name: str | None = None


class GeminiKeywordSuggestionOutput(BaseModel):
    focus_keyphrase: str = Field(..., min_length=2, max_length=120)
    secondary_keywords: list[str] = Field(default_factory=list, max_length=10)
    anchor_text_variations: list[str] = Field(default_factory=list, max_length=8)
    image_alt_suggestions: list[str] = Field(default_factory=list, max_length=5)


def _smart_title_case(phrase: str) -> str:
    words = [w for w in re.split(r"\s+", phrase.strip()) if w]
    if not words:
        return ""
    minor = {"vs", "and", "or", "in", "on", "of", "to", "for", "with", "at", "by"}
    styled: list[str] = []
    for idx, word in enumerate(words):
        low = word.lower()
        if idx > 0 and low in minor:
            styled.append(low)
        elif word.isupper() and len(word) <= 5:
            styled.append(word)
        else:
            styled.append(word[:1].upper() + word[1:])
    return " ".join(styled)


def _strip_brand_suffix(text: str, *, brand_names: list[str]) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return ""
    for sep in (" | ", " - ", " — ", " :: "):
        if sep in cleaned:
            parts = [p.strip() for p in cleaned.split(sep) if p.strip()]
            if len(parts) > 1:
                tail_low = parts[-1].lower()
                if any(b and b in tail_low for b in brand_names) or len(parts[-1]) <= 24:
                    cleaned = sep.join(parts[:-1]).strip()
                    break
    return cleaned


def _extract_core_phrase(raw: str, *, brand_names: list[str]) -> str:
    stripped = _strip_brand_suffix(raw, brand_names=brand_names)
    if not stripped:
        return ""
    match = _QUESTION_SPLITS.split(stripped, maxsplit=1)
    head = (match[0] if match else stripped).strip(" -:?!.,")
    if len(head.split()) >= 2:
        return _smart_title_case(head)[:180]
    if len(stripped.split()) <= 7:
        return _smart_title_case(stripped.rstrip("?.!"))[:180]
    words = stripped.rstrip("?.!").split()[:6]
    return _smart_title_case(" ".join(words))[:180]


def _strip_author_attribution(text: str, author: str | None) -> str:
    """Remove a known author only when it is formatted as a title/byline prefix or suffix."""
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    name = re.sub(r"\s+", " ", author or "").strip()
    if not cleaned or not name:
        return cleaned

    escaped_name = re.escape(name)
    cleaned = re.sub(
        rf"^\s*(?:by\s+)?{escaped_name}(?:\s*(?::|\||—|–|-)\s*|\s+)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        rf"\s*(?:(?:\||—|–|-)\s*|,\s*|by\s+|\s+){escaped_name}\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" \t:|—–-,")


def _slug_to_phrase(url: str) -> str:
    path = urlparse(url).path or "/"
    segments = [unquote(seg) for seg in path.split("/") if seg and not seg.isdigit()]
    if not segments:
        return ""
    raw_slug = _FILE_EXT_RE.sub("", segments[-1])
    if raw_slug.lower() in {"index", "home"} and len(segments) > 1:
        raw_slug = segments[-2]
    tokens = [t for t in re.split(r"[-_]+", raw_slug) if t and not t.isdigit()]
    # Trim leading/trailing conversational noise tokens cleanly while preserving comparison slugs
    while len(tokens) > 2 and tokens[-1].lower() in {
        "difference",
        "the",
        "whats",
        "what",
        "is",
        "guide",
        "overview",
        "explained",
    }:
        tokens.pop()
    if not tokens:
        return ""
    return _smart_title_case(" ".join(tokens[:8]))


def _extract_markdown_headings(markdown: str | None) -> list[str]:
    if not markdown:
        return []
    headings: list[str] = []
    for line in markdown.splitlines():
        m = re.match(r"^#{1,3}\s+(.+)$", line.strip())
        if m:
            txt = re.sub(r"[`*_#\[\]]", "", m.group(1)).strip()
            if 3 <= len(txt) <= 120:
                headings.append(txt)
    return headings


def _extract_structured_keywords(structured_data: dict[str, Any] | None) -> list[str]:
    if not isinstance(structured_data, dict):
        return []
    out: list[str] = []
    raw_kw = structured_data.get("keywords")
    if isinstance(raw_kw, str):
        out.extend([p.strip() for p in raw_kw.split(",") if p.strip()])
    elif isinstance(raw_kw, list):
        out.extend([str(p).strip() for p in raw_kw if str(p).strip()])
    headline = structured_data.get("headline")
    if isinstance(headline, str) and headline.strip():
        out.append(headline.strip())
    return out


def _image_filename_description(image_url: str) -> str:
    path = urlparse(image_url).path or ""
    filename = unquote(path.rsplit("/", 1)[-1])
    stem = _FILE_EXT_RE.sub("", filename)
    tokens = [t for t in re.split(r"[-_\s]+", stem) if t and not re.fullmatch(r"\d+(?:x\d+)?", t)]
    filtered = [t for t in tokens if len(t) > 1]
    if len(filtered) >= 2:
        return " ".join(filtered[:8]).capitalize()
    return ""


def _build_image_alt_suggestions(
    *,
    title: str,
    focus_keyphrase: str,
    featured_image_url: str | None,
    featured_image_alt: str | None,
    images: list[dict[str, Any]] | None,
    h1_text: str | None,
) -> list[dict[str, Any]]:
    """Build factual accessibility-focused alt text suggestions without keyword stuffing."""
    suggestions: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    topic_subject = (h1_text or focus_keyphrase or title or "page visual").strip()
    if len(topic_subject) > 90:
        topic_subject = topic_subject[:87].rstrip() + "..."

    candidates: list[dict[str, Any]] = []
    if featured_image_url:
        candidates.append(
            {
                "url": featured_image_url,
                "alt": featured_image_alt,
                "context": "Featured article image",
            }
        )
    for img in images or []:
        if not isinstance(img, dict):
            continue
        url = str(img.get("url") or img.get("image_url") or "").strip()
        if not url:
            continue
        candidates.append(
            {
                "url": url,
                "alt": img.get("alt") or img.get("current_alt"),
                "context": str(img.get("context") or "Inline content image"),
            }
        )

    for entry in candidates:
        url = str(entry.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        cur_alt = str(entry.get("alt") or "").strip() or None
        file_desc = _image_filename_description(url)
        if cur_alt and len(cur_alt.split()) >= 3:
            suggested = cur_alt[:250]
        elif file_desc:
            suggested = f"Illustration of {file_desc.lower()} for {topic_subject}"[:250]
        else:
            suggested = f"Editorial visual depicting {topic_subject}"[:250]

        suggestions.append(
            ImageAltSuggestionItem(
                image_url=url[:2048],
                current_alt=cur_alt[:300] if cur_alt else None,
                suggested_alt=suggested,
                context=str(entry.get("context") or "Content image")[:160],
            ).model_dump()
        )
        if len(suggestions) >= 6:
            break

    return suggestions


def _dedupe_phrases(candidates: list[str], *, exclude_norm: str = "", limit: int = 8) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    if exclude_norm:
        seen.add(exclude_norm)
    for item in candidates:
        clean = re.sub(r"\s+", " ", item or "").strip(" ,;:-")
        if len(clean) < 3 or len(clean) > 120:
            continue
        norm = normalize_keyphrase(clean)
        if not norm or norm in seen:
            continue
        # Avoid low-information single-word fragments unless uppercase acronyms
        if len(clean.split()) == 1 and len(clean) < 5:
            continue
        seen.add(norm)
        results.append(clean)
        if len(results) >= limit:
            break
    return results


def build_synced_anchor_texts(focus_keyphrase: str, secondary_keywords: list[str]) -> list[str]:
    """The only deterministic anchor-text derivation used by keyword mappings."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in [focus_keyphrase, *secondary_keywords]:
        clean = re.sub(r"\s+", " ", str(raw or "")).strip()
        norm = normalize_keyphrase(clean)
        if clean and norm and norm not in seen:
            seen.add(norm)
            out.append(clean)
    return out


def extract_game_metadata(
    *,
    content: WebsiteContent,
    website: Website | None = None,
) -> tuple[str, str]:
    structured = content.structured_data_json if isinstance(content.structured_data_json, dict) else {}
    brand = (
        str((website.brand_name if website and website.brand_name else None) or
            (website.name if website and website.name else "") or "")
        .strip()
    )

    game_name = ""
    provider_name = ""
    for key in ("name", "gameName", "game_name"):
        value = structured.get(key)
        if isinstance(value, str) and value.strip():
            game_name = value.strip()
            break
    for key in ("provider", "providerName", "provider_name", "publisher", "brand",
                "manufacturer", "creator"):
        value = structured.get(key)
        if isinstance(value, str) and value.strip():
            provider_name = value.strip()
            break
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name.strip():
                provider_name = name.strip()
                break

    if not game_name:
        candidates = [content.h1_text, content.title]
        for candidate in candidates:
            if candidate:
                cleaned = re.sub(
                    r"\s+(?:slots?|slot games?|online slots?|casino games?|demo|review|play)\s*$",
                    "",
                    candidate.strip(),
                    flags=re.I,
                )
                cleaned = re.sub(r"\s*(?:\||—|::|\s+-)\s*.*$", "", cleaned).strip()
                if cleaned:
                    game_name = cleaned[:120]
                    break
    if not game_name:
        game_name = _slug_to_phrase(content.canonical_url or content.url).replace(" Slot Game", "")

    if not provider_name:
        text_blob = " ".join(
            [
                content.meta_description or "",
                content.h1_text or "",
                content.title or "",
                content.markdown_content or "",
            ]
        )
        match = re.search(
            r"(?:provider|developer|studio|software|publisher)\s*[:\-]\s*([A-Za-z0-9'&.+\- ]{2,45})",
            text_blob,
            flags=re.I,
        )
        if match:
            provider_name = re.split(r"[,\n|;]", match.group(1))[0].strip()
        elif brand:
            provider_name = ""  # Brand is not automatically a provider.

    if provider_name.lower() in {"slot", "slots", "game", "games", "casino", brand.lower()}:
        provider_name = ""
    return game_name.strip(), provider_name.strip()


def build_game_page_keywords(
    *,
    content: WebsiteContent,
    website: Website | None = None,
) -> SuggestedKeywordsResult:
    game_name, provider_name = extract_game_metadata(content=content, website=website)
    if not game_name:
        return SuggestedKeywordsResult(
            focus_keyphrase="",
            secondary_keywords=[],
            anchor_text_variations=[],
            image_alt_suggestions=[],
            keyword_generation_status="needs_metadata",
            game_name=None,
            provider_name=provider_name or None,
        )

    brand_name = (
        str((website.brand_name if website and website.brand_name else None) or
            (website.name if website and website.name else "") or "").strip()
    )
    focus = f"{game_name} slots"
    secondary: list[str] = [f"{game_name} provider"]
    if provider_name:
        secondary.append(f"{game_name} {provider_name} slots")
        secondary.append(provider_name)
    secondary.append(game_name)
    if brand_name:
        secondary.append(f"{game_name} {brand_name}")
    secondary.append(f"{game_name} slot game")
    secondary = _dedupe_phrases(secondary, exclude_norm=normalize_keyphrase(focus), limit=8)
    anchors = build_synced_anchor_texts(focus, secondary)
    return SuggestedKeywordsResult(
        focus_keyphrase=focus,
        secondary_keywords=secondary,
        anchor_text_variations=anchors,
        image_alt_suggestions=[],
        suggestion_source="template_generated",
        keyword_generation_method="template",
        keyword_generation_status="generated",
        keyword_evidence=[{"source": "structured_game_metadata", "game_name": game_name,
                           "provider_name": provider_name or None}],
        keyword_scores={"game_template": 100, "provider_present": bool(provider_name)},
        game_name=game_name,
        provider_name=provider_name or None,
    )


def suggest_keywords_for_content(
    *,
    content: WebsiteContent,
    website: Website | None = None,
    knowledge: WebsiteKnowledgeProfile | None = None,
    extracted_headings: list[str] | list[dict[str, str]] | None = None,
    extracted_images: list[dict[str, Any]] | None = None,
    featured_image_url: str | None = None,
    featured_image_alt: str | None = None,
) -> SuggestedKeywordsResult:
    """Deterministically suggest focus keyphrase, secondary keywords, anchor texts & image alts."""
    if content.content_type == "game_page":
        result = build_game_page_keywords(content=content, website=website)
        if result.keyword_generation_status == "needs_metadata":
            return result
        result = SuggestedKeywordsResult(
            focus_keyphrase=result.focus_keyphrase,
            secondary_keywords=result.secondary_keywords,
            anchor_text_variations=result.anchor_text_variations,
            image_alt_suggestions=_build_image_alt_suggestions(
                title=content.title or "",
                focus_keyphrase=result.focus_keyphrase,
                featured_image_url=featured_image_url,
                featured_image_alt=featured_image_alt,
                images=extracted_images,
                h1_text=content.h1_text,
            ),
            suggestion_source=result.suggestion_source,
            keyword_generation_method=result.keyword_generation_method,
            keyword_generation_status=result.keyword_generation_status,
            keyword_evidence=result.keyword_evidence,
            keyword_scores=result.keyword_scores,
            game_name=result.game_name,
            provider_name=result.provider_name,
        )
        return result

    brand_names = []
    if website:
        for candidate_b in (website.brand_name, website.name):
            if candidate_b:
                brand_names.append(candidate_b.strip().lower())
    if knowledge and knowledge.brand_name:
        brand_names.append(knowledge.brand_name.strip().lower())

    h1_clean = (content.h1_text or "").strip()
    title_clean = (content.title or "").strip()
    author_name = content.author if content.content_type == "blog_post" else None
    h1_focus_source = _strip_author_attribution(h1_clean, author_name)
    title_focus_source = _strip_author_attribution(title_clean, author_name)
    slug_phrase = _slug_to_phrase(content.canonical_url or content.url)

    heading_texts: list[str] = []
    for h in extracted_headings or []:
        if isinstance(h, str) and h.strip():
            heading_texts.append(h.strip())
        elif isinstance(h, dict) and str(h.get("text") or "").strip():
            heading_texts.append(str(h["text"]).strip())
    heading_texts.extend(_extract_markdown_headings(content.markdown_content))
    if author_name:
        heading_texts = [
            _strip_author_attribution(heading, author_name)
            for heading in heading_texts
        ]
        heading_texts = [heading for heading in heading_texts if heading]

    structured_kw = _extract_structured_keywords(content.structured_data_json)
    yake_kw = [str(k).strip() for k in (content.keywords or []) if str(k).strip()]
    if author_name:
        structured_kw = [
            _strip_author_attribution(phrase, author_name)
            for phrase in structured_kw
        ]
        structured_kw = [phrase for phrase in structured_kw if phrase]
        yake_kw = [
            _strip_author_attribution(phrase, author_name)
            for phrase in yake_kw
        ]
        yake_kw = [phrase for phrase in yake_kw if phrase]

    # Pick primary focus keyphrase candidate cleanly without requiring Gemini
    title_core = _extract_core_phrase(
        h1_focus_source or title_focus_source,
        brand_names=brand_names,
    )
    focus_candidates = [
        slug_phrase if (slug_phrase and 2 <= len(slug_phrase.split()) <= 7) else "",
        title_core,
        _smart_title_case(structured_kw[0]) if structured_kw else "",
        _smart_title_case(yake_kw[0]) if yake_kw else "",
        title_focus_source[:120],
    ]
    focus = ""
    for cand in focus_candidates:
        clean_cand = re.sub(r"\s+", " ", cand or "").strip(" -:?!.,")
        if author_name and normalize_keyphrase(clean_cand) == normalize_keyphrase(author_name):
            continue
        if len(clean_cand) >= 3:
            # Prefer title_core casing if slug_phrase closely matches title_core
            if (
                title_core
                and fuzz.token_set_ratio(clean_cand.lower(), title_core.lower()) >= 88
                and len(title_core.split()) <= len(clean_cand.split()) + 1
            ):
                focus = title_core
            else:
                focus = clean_cand
            break

    if not focus:
        focus = _smart_title_case(slug_phrase or title_clean or content.content_type)[:120]

    focus_norm = normalize_keyphrase(focus)

    # Assemble rich, factual secondary keyword candidates from headings, meta, YAKE & profile
    secondary_pool: list[str] = []
    if h1_focus_source and normalize_keyphrase(h1_focus_source) != focus_norm:
        secondary_pool.append(
            _strip_brand_suffix(h1_focus_source, brand_names=brand_names).rstrip("?!.")
        )
    for heading in heading_texts:
        h_core = _strip_brand_suffix(heading, brand_names=brand_names).rstrip("?!.")
        if h_core and normalize_keyphrase(h_core) != focus_norm:
            secondary_pool.append(h_core)
    if content.meta_description:
        for fragment in re.split(r"[.;|•\n]", content.meta_description):
            frag = fragment.strip()
            if 2 <= len(frag.split()) <= 7:
                secondary_pool.append(frag)
    for kw in [*structured_kw, *yake_kw]:
        secondary_pool.append(kw)
    if knowledge and knowledge.main_keywords:
        for pk in knowledge.main_keywords:
            if any(tok in (title_clean + " " + focus).lower() for tok in pk.lower().split()):
                secondary_pool.append(pk)
    if website and website.keyword_bank:
        secondary_pool.extend(website.keyword_bank)

    secondary = _dedupe_phrases(secondary_pool, exclude_norm=focus_norm, limit=8)

    anchors = build_synced_anchor_texts(focus, secondary)

    featured_img = None
    if content.featured_image_alt if hasattr(content, "featured_image_alt") else None:
        featured_img = getattr(content, "featured_image_alt", None)
    # Also inspect structured_data / markdown for image links if extracted_images not passed
    md_images: list[dict[str, Any]] = list(extracted_images or [])
    if not md_images and content.markdown_content:
        for alt_txt, img_url in re.findall(
            r"!\[([^\]]*)\]\((https?://[^)\s]+)\)", content.markdown_content
        ):
            md_images.append({"url": img_url, "alt": alt_txt, "context": "Markdown image"})

    alts = _build_image_alt_suggestions(
        title=title_clean,
        focus_keyphrase=focus,
        featured_image_url=featured_image_url,
        featured_image_alt=featured_image_alt or featured_img,
        images=md_images,
        h1_text=h1_clean,
    )

    return SuggestedKeywordsResult(
        focus_keyphrase=focus[:255],
        secondary_keywords=secondary,
        anchor_text_variations=anchors,
        image_alt_suggestions=alts,
        suggestion_source="python_auto",
        keyword_generation_method="python",
        keyword_generation_status="generated",
        keyword_evidence=[
            {"source": "meta_title", "value": content.title, "weight": 10},
            {"source": "meta_description", "value": content.meta_description, "weight": 8},
            {"source": "h1", "value": h1_clean or None, "weight": 7},
            {"source": "url_slug", "value": slug_phrase or None, "weight": 5},
            {"source": "h2_h3_headings", "value": heading_texts[:20], "weight": 4},
        ],
        keyword_scores={
            focus_norm: {
                "focus_keyphrase": focus,
                "score": sum(
                    weight
                    for weight, present in (
                        (10, bool(title_clean)),
                        (8, bool(content.meta_description)),
                        (7, bool(h1_clean)),
                        (5, bool(slug_phrase)),
                        (4, bool(heading_texts)),
                        (3, bool(content.markdown_content)),
                        (1, bool(content.extracted_content)),
                    )
                    if present
                ),
                "source_count": len(
                    {k for k, v in {
                        "meta_title": bool(title_clean),
                        "meta_description": bool(content.meta_description),
                        "h1": bool(h1_clean),
                        "url_slug": bool(slug_phrase),
                        "h2_h3": bool(heading_texts),
                        "main_content": bool(content.extracted_content),
                    }.items() if v}
                ),
            }
        },
    )


def detect_cannibalization_warnings(
    *,
    content_id: int,
    focus_keyphrase: str,
    sibling_records: list[tuple[ContentKeyword, WebsiteContent]],
) -> list[CannibalizationMatchResponse]:
    """Detect non-blocking focus keyphrase overlap across URLs of the same website."""
    norm = normalize_keyphrase(focus_keyphrase)
    if not norm or len(norm) < 2:
        return []

    warnings: list[CannibalizationMatchResponse] = []
    for sib_kw, sib_content in sibling_records:
        if sib_content.id == content_id or sib_content.is_excluded:
            continue
        if sib_kw.approval_status == "rejected":
            continue
        sib_norm = normalize_keyphrase(sib_kw.focus_keyphrase)
        if not sib_norm:
            continue

        if sib_norm == norm:
            warnings.append(
                CannibalizationMatchResponse(
                    content_id=sib_content.id,
                    title=sib_content.title,
                    canonical_url=sib_content.canonical_url,
                    content_type=sib_content.content_type,
                    focus_keyphrase=sib_kw.focus_keyphrase,
                    approval_status=sib_kw.approval_status,
                    similarity_score=100.0,
                    severity="high",
                    reason="Exact focus keyphrase match on another URL in this website.",
                )
            )
            continue

        score = float(fuzz.token_set_ratio(norm, sib_norm))
        # Guard against short words creating false overlap
        if score >= 82.0 and (len(norm.split()) >= 2 or len(sib_norm.split()) >= 2):
            warnings.append(
                CannibalizationMatchResponse(
                    content_id=sib_content.id,
                    title=sib_content.title,
                    canonical_url=sib_content.canonical_url,
                    content_type=sib_content.content_type,
                    focus_keyphrase=sib_kw.focus_keyphrase,
                    approval_status=sib_kw.approval_status,
                    similarity_score=round(score, 1),
                    severity="medium",
                    reason="Highly similar focus keyphrase used by another URL on this site.",
                )
            )

    warnings.sort(key=lambda w: (-w.similarity_score, w.content_id))
    return warnings[:10]
