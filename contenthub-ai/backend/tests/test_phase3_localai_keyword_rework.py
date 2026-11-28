from app.models.website import Website
from app.models.website_content import WebsiteContent
from app.services.ai.localai import normalize_localai_base_url
from app.services.content.keyword_suggester import (
    build_synced_anchor_texts,
    suggest_keywords_for_content,
)


def test_localai_base_url_normalization():
    assert normalize_localai_base_url("") == "http://127.0.0.1:8081"
    assert normalize_localai_base_url("http://127.0.0.1:8081/v1") == "http://127.0.0.1:8081"
    assert normalize_localai_base_url("http://127.0.0.1:8081/v1/") == "http://127.0.0.1:8081"
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


def test_localai_list_provider_models_refresh_uses_localai_provider(
    monkeypatch: object,
    test_settings: object,
    memory_repos: dict,
) -> None:
    from app.services.ai.localai import LocalAiProvider
    from app.services.ai.management_service import AiManagementService
    from app.services.ai.provider import ProviderModelDescriptor

    class ExplodingGeminiClient:
        def list_models(self, *, api_key: str, timeout_seconds: int = 30):
            raise AssertionError("GeminiSdkProvider/client must not be called for localai refresh")

    monkeypatch.setattr(
        LocalAiProvider,
        "list_models",
        lambda self, *, base_url, api_key=None, timeout_seconds=30: [
            ProviderModelDescriptor(
                name="qwen2.5-7b-instruct",
                display_name="Qwen 2.5 7B Instruct",
                description="LocalAI GGUF chat model",
                is_flash_recommended=False,
            )
        ],
    )

    provider = memory_repos["ai"].create_provider(
        {
            "name": "LocalAI Node",
            "provider_type": "localai",
            "base_url": "http://127.0.0.1:8080/v1",
            "encrypted_api_key": None,
            "selected_model": "qwen2.5-7b-instruct",
            "is_active": True,
            "is_default": False,
        }
    )

    svc = AiManagementService(
        settings=test_settings,
        ai_repo=memory_repos["ai"],
        website_repo=memory_repos["websites"],
        activity_repo=memory_repos["activities"],
        provider_client=ExplodingGeminiClient(),
    )
    res = svc.list_provider_models(provider.id, refresh=True)
    assert res.fetched_live is True
    assert [m.name for m in res.models] == ["qwen2.5-7b-instruct"]


def test_localai_select_keywords_supports_reasoning_and_fenced_json(monkeypatch: object) -> None:
    import httpx

    from app.services.ai.localai import LocalAiProvider

    def _fake_post(self, base_url: str, method: str, path: str, **kwargs: object) -> httpx.Response:
        assert method == "POST" and path == "/chat/completions"
        payload = {
            "model": "qwen3.8-9b-q4",
            "usage": {"prompt_tokens": 28, "completion_tokens": 18, "total_tokens": 46},
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning": (
                            '```json\n{"primary_focus_keyphrase": "Fixed Odds vs Dynamic Odds", '
                            '"secondary_keywords": ["Fixed odds explained"]}\n```'
                        ),
                    },
                }
            ]
        }
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(LocalAiProvider, "_request", _fake_post)
    out, result = LocalAiProvider().select_keywords(
        base_url="http://127.0.0.1:8081/v1",
        api_key="",
        model_name="qwen3.5-4b-claude-4.6-opus-reasoning-distilled",
        system_instruction="sys",
        user_prompt="usr",
    )
    assert result.model_name == "qwen3.8-9b-q4"
    assert result.measured_input_tokens == 28
    assert result.measured_output_tokens == 18
    assert result.total_measured_tokens == 46
    assert result.raw_usage_available is True
    assert "Fixed Odds vs Dynamic Odds" in result.raw_text
    assert out.focus_keyphrase == "Fixed Odds vs Dynamic Odds"
    assert out.secondary_keywords == ["Fixed odds explained"]
