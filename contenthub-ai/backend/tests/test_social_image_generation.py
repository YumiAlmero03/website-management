from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.core.dependencies import (
    get_social_image_generation_service,
    get_social_post_service,
)
from app.core.security import encrypt_secret
from app.models.media_asset import MediaAsset
from app.services.ai.exceptions import AiProviderNotConfiguredError, AiResponseValidationError
from app.services.ai.gemini import GeminiSdkProvider
from app.services.social_image_generation_service import SocialImageGenerationService


def _png_bytes() -> bytes:
    import io

    image = Image.new("RGB", (2, 2), color="teal")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeImageProvider:
    def __init__(self, image_bytes: bytes) -> None:
        self.image_bytes = image_bytes
        self.call: dict[str, Any] | None = None

    def generate_image(
        self,
        *,
        api_key: str,
        model_name: str,
        prompt: str,
        timeout_seconds: int = 45,
    ) -> bytes:
        self.call = {
            "api_key": api_key,
            "model_name": model_name,
            "prompt": prompt,
            "timeout_seconds": timeout_seconds,
        }
        return self.image_bytes


def test_social_image_is_validated_persisted_and_website_scoped(
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    key = "test-gemini-image-key"
    memory_repos["ai"].create_provider(
        {
            "name": "Image Gemini",
            "provider_type": "gemini",
            "encrypted_api_key": encrypt_secret(key, test_settings.app_encryption_key),
            "is_default": True,
            "is_active": True,
            "generation_enabled": True,
        }
    )
    image_provider = FakeImageProvider(_png_bytes())
    service = SocialImageGenerationService(
        settings=test_settings,
        ai_repo=memory_repos["ai"],
        media_repo=memory_repos["media"],
        provider_client=image_provider,
    )

    asset = service.generate_for_website(
        website_id=42,
        prompt="A colorful editorial scene about safer online play",
    )

    assert asset.website_id == 42
    assert asset.file_path is not None
    assert (test_settings.resolved_storage_root / asset.file_path).is_file()
    assert asset.mime_type == "image/png"
    assert asset.width == 2 and asset.height == 2
    assert image_provider.call is not None
    assert image_provider.call["api_key"] == key
    assert image_provider.call["model_name"] == "imagen-3.0-generate-002"
    assert "Do not include text, logos, or watermarks." in image_provider.call["prompt"]
    assert "safer online play" in image_provider.call["prompt"]


def test_social_image_rejects_invalid_provider_output(
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    memory_repos["ai"].create_provider(
        {
            "name": "Image Gemini",
            "provider_type": "gemini",
            "encrypted_api_key": encrypt_secret("test-key", test_settings.app_encryption_key),
            "is_default": True,
            "is_active": True,
            "generation_enabled": True,
        }
    )
    service = SocialImageGenerationService(
        settings=test_settings,
        ai_repo=memory_repos["ai"],
        media_repo=memory_repos["media"],
        provider_client=FakeImageProvider(b"not an image"),
    )

    with pytest.raises(AiResponseValidationError, match="Invalid or corrupted image file"):
        service.generate_for_website(website_id=42, prompt="An editorial image prompt")

    assert memory_repos["media"].list_paginated(page=1, page_size=20)[1] == 0


def test_social_image_requires_an_active_default_gemini_provider(
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    service = SocialImageGenerationService(
        settings=test_settings,
        ai_repo=memory_repos["ai"],
        media_repo=memory_repos["media"],
        provider_client=FakeImageProvider(_png_bytes()),
    )

    with pytest.raises(AiProviderNotConfiguredError, match="active Gemini provider"):
        service.generate_for_website(website_id=42, prompt="An editorial image prompt")


def test_gemini_image_adapter_requests_one_image(monkeypatch: pytest.MonkeyPatch) -> None:
    call_args: dict[str, Any] = {}

    class FakeModels:
        def generate_images(self, **kwargs: Any) -> Any:
            call_args.update(kwargs)
            image = SimpleNamespace(image_bytes=b"generated-image")
            return SimpleNamespace(generated_images=[SimpleNamespace(image=image)])

    provider = GeminiSdkProvider()
    monkeypatch.setattr(
        provider,
        "_create_client",
        lambda **_kwargs: SimpleNamespace(models=FakeModels()),
    )

    result = provider.generate_image(
        api_key="key",
        model_name="imagen-3.0-generate-002",
        prompt="A small test image",
    )

    assert result == b"generated-image"
    assert call_args["model"] == "imagen-3.0-generate-002"
    assert call_args["config"].number_of_images == 1


def test_generate_image_route_uses_draft_website_and_csrf(
    app: FastAPI,
    auth_client: tuple[TestClient, str],
) -> None:
    client, csrf = auth_client
    asset = MediaAsset(
        id=1,
        website_id=42,
        file_name="generated.png",
        file_path="images/generated.png",
        source_url=None,
        mime_type="image/png",
        file_size=10,
        width=2,
        height=2,
        alt_text="Generated",
        checksum="a" * 64,
        created_at=datetime(2026, 1, 1),
    )
    calls: dict[str, Any] = {}

    class FakePostService:
        def get_post(self, post_id: int) -> Any:
            calls["post_id"] = post_id
            return SimpleNamespace(website_id=42)

    class FakeImageService:
        def generate_for_website(self, *, website_id: int, prompt: str) -> MediaAsset:
            calls["website_id"] = website_id
            calls["prompt"] = prompt
            return asset

    app.dependency_overrides[get_social_post_service] = lambda: FakePostService()
    app.dependency_overrides[get_social_image_generation_service] = lambda: FakeImageService()

    response = client.post(
        "/api/v1/social-posts/9/generate-image",
        headers={"X-CSRF-Token": csrf},
        json={"prompt": "The unsaved draft caption"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["id"] == 1
    assert calls == {"post_id": 9, "website_id": 42, "prompt": "The unsaved draft caption"}
    assert client.post(
        "/api/v1/social-posts/9/generate-image",
        json={"prompt": "The unsaved draft caption"},
    ).status_code == 403
