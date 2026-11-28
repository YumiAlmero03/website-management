from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.config import Settings
from app.core.security import decrypt_secret
from app.models.media_asset import MediaAsset
from app.repositories.ai_repo import AiRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.services.ai.exceptions import AiProviderNotConfiguredError, AiResponseValidationError
from app.services.content.media import (
    ALLOWED_IMAGE_MIMES,
    MediaValidationError,
    validate_image_bytes,
)

IMAGEN_MODEL = "imagen-3.0-generate-002"


class ImageGenerationProvider(Protocol):
    def generate_image(
        self,
        *,
        api_key: str,
        model_name: str,
        prompt: str,
        timeout_seconds: int = 45,
    ) -> bytes: ...


class SocialImageGenerationService:
    def __init__(
        self,
        *,
        settings: Settings,
        ai_repo: AiRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        provider_client: ImageGenerationProvider,
    ) -> None:
        self.settings = settings
        self.ai_repo = ai_repo
        self.media_repo = media_repo
        self.provider_client = provider_client

    def _api_key(self) -> str:
        provider = self.ai_repo.get_default_provider()
        if provider is None or provider.provider_type != "gemini":
            raise AiProviderNotConfiguredError(
                "Set an active Gemini provider as the default to generate images."
            )
        if not provider.generation_enabled:
            raise AiProviderNotConfiguredError(
                "Image generation is disabled for the default Gemini provider."
            )
        if provider.encrypted_api_key:
            return decrypt_secret(provider.encrypted_api_key, self.settings.app_encryption_key)
        if self.settings.gemini_api_key.strip():
            return self.settings.gemini_api_key.strip()
        raise AiProviderNotConfiguredError(
            "The default Gemini provider does not have an API key configured."
        )

    def generate_for_website(
        self,
        *,
        website_id: int,
        prompt: str,
    ) -> MediaAsset:
        cleaned_prompt = prompt.strip()
        if len(cleaned_prompt) < 5 or len(cleaned_prompt) > 1500:
            raise AiResponseValidationError("Image prompt must be between 5 and 1500 characters.")

        image_bytes = self.provider_client.generate_image(
            api_key=self._api_key(),
            model_name=IMAGEN_MODEL,
            prompt=(
                "Create a polished, editorial-quality social media image that visually "
                "represents this post. Do not include text, logos, or watermarks.\n\n"
                f"Post context: {cleaned_prompt}"
            ),
            timeout_seconds=self.settings.ai_request_timeout_seconds,
        )
        try:
            mime_type, width, height, checksum = validate_image_bytes(
                image_bytes,
                max_file_bytes=self.settings.media_max_file_bytes,
                max_dimension_px=self.settings.media_max_dimension_px,
            )
        except MediaValidationError as exc:
            raise AiResponseValidationError(str(exc)) from exc
        extension = ALLOWED_IMAGE_MIMES[mime_type]
        filename = f"social_{website_id}_{uuid4().hex}.{extension}"
        relative_path = Path("images") / filename
        destination = self.settings.resolved_storage_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            destination.write_bytes(image_bytes)
            return self.media_repo.create(
                website_id=website_id,
                file_name=filename,
                file_path=relative_path.as_posix(),
                source_url=None,
                mime_type=mime_type,
                file_size=len(image_bytes),
                width=width,
                height=height,
                alt_text=f"AI-generated social image: {cleaned_prompt[:220]}",
                checksum=checksum,
            )
        except Exception:
            with suppress(OSError):
                destination.unlink(missing_ok=True)
            raise
