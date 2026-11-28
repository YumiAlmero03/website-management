from app.models.website import Website
from app.models.website_content import WebsiteContent
from app.services.ai.localai import normalize_localai_base_url
from app.services.content.keyword_suggester import (
    build_synced_anchor_texts,
    suggest_keywords_for_content,
)


def test_localai_base_url_normalization():
    assert normalize_localai_base_url("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080"
    assert normalize_localai_base_url("http://127.0.0.1:8080/v1/") == "http://127.0.0.1:8080"
    assert normalize_localai_base_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"


def test_exact_game_template_and_anchor_sync():
    website = Website(
        name="Bygame",
        domain="bygame.ph",
        brand_name="Bygame",
        category_id=1,
        website_type="wordpress",
    )
    content = WebsiteContent(
        website_id=1,
        content_type="game_page",
        url="https://bygame.ph/game/gates-of-olympus",
        canonical_url="https://bygame.ph/game/gates-of-olympus",
        url_hash="game-test",
        title="Gates of Olympus",
        h1_text="Gates of Olympus",
        structured_data_json={"provider": "Pragmatic Play"},
        content_hash="game-content",
    )

    result = suggest_keywords_for_content(content=content, website=website)

    assert result.focus_keyphrase == "Gates of Olympus slots"
    assert result.secondary_keywords == [
        "Gates of Olympus provider",
        "Gates of Olympus Pragmatic Play slots",
        "Pragmatic Play",
        "Gates of Olympus",
        "Gates of Olympus Bygame",
        "Gates of Olympus slot game",
    ]
    assert result.anchor_text_variations == [
        "Gates of Olympus slots",
        *result.secondary_keywords,
    ]


def test_anchor_texts_are_exact_primary_plus_secondary():
    anchors = build_synced_anchor_texts(
        "Fixed Odds vs Dynamic Odds",
        ["Fixed odds", "Dynamic odds", "Fixed odds"],
    )
    assert anchors == [
        "Fixed Odds vs Dynamic Odds",
        "Fixed odds",
        "Dynamic odds",
    ]


def test_blog_focus_keyphrase_excludes_author_attribution():
    content = WebsiteContent(
        website_id=1,
        content_type="blog_post",
        url="https://bygame.ph/blog/article",
        canonical_url="https://bygame.ph/blog/article",
        url_hash="blog-author-test",
        title="Maria Santos: Fixed Odds vs Dynamic Odds",
        author="Maria Santos",
        h1_text="Maria Santos: Fixed Odds vs Dynamic Odds",
        content_hash="blog-author-content",
    )

    result = suggest_keywords_for_content(content=content)

    assert result.focus_keyphrase == "Fixed Odds vs Dynamic Odds"


def test_blog_focus_keyphrase_excludes_author_suffix():
    content = WebsiteContent(
        website_id=1,
        content_type="blog_post",
        url="https://bygame.ph/blog/article",
        canonical_url="https://bygame.ph/blog/article",
        url_hash="blog-author-suffix-test",
        title="Fixed Odds vs Dynamic Odds by Maria Santos",
        author="Maria Santos",
        h1_text="Fixed Odds vs Dynamic Odds",
        content_hash="blog-author-suffix-content",
    )

    result = suggest_keywords_for_content(content=content)

    assert result.focus_keyphrase == "Fixed Odds vs Dynamic Odds"
