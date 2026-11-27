from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from app.config import Settings
from app.models.media_asset import MediaAsset
from app.repositories.media_repo import MediaRepositoryProtocol
from app.services.scanner.exceptions import ScannerError
from app.services.scanner.security import SafeHttpFetcher, validate_outbound_url

ALLOWED_IMAGE_MIMES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

PILLOW_FORMAT_TO_MIME: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


class MediaValidationError(Exception):
    """Raised when an image fails MIME, size, dimension, or Pillow validation."""


def validate_image_bytes(
    data: bytes,
    *,
    max_file_bytes: int,
    max_dimension_px: int,
    declared_mime: str | None = None,
) -> tuple[str, int, int, str]:
    """Validate image bytes with Pillow and return (mime_type, width, height, sha256_checksum)."""
    if not data:
        raise MediaValidationError("Image payload is empty.")
    if len(data) > max_file_bytes:
        raise MediaValidationError(
            f"Image exceeds maximum file size ({len(data)} > {max_file_bytes} bytes)."
        )

    # Guard against Pillow decompression bombs.
    Image.MAX_IMAGE_PIXELS = max_dimension_px * max_dimension_px

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            fmt = (img.format or "").upper()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise MediaValidationError(f"Invalid or corrupted image file: {exc}") from exc

    resolved_mime = PILLOW_FORMAT_TO_MIME.get(fmt)
    if resolved_mime is None:
        raise MediaValidationError(f"Unsupported image format: '{fmt or 'unknown'}'.")

    if declared_mime:
        clean_declared = declared_mime.split(";", 1)[0].strip().lower()
        if (
            clean_declared
            and clean_declared not in ALLOWED_IMAGE_MIMES
            and clean_declared != "application/octet-stream"
        ):
            raise MediaValidationError(f"Unsupported declared MIME type: '{clean_declared}'.")

    if width <= 0 or height <= 0 or width > max_dimension_px or height > max_dimension_px:
        raise MediaValidationError(
            f"Image dimensions ({width}x{height}) exceed limit ({max_dimension_px}px)."
        )

    checksum = hashlib.sha256(data).hexdigest()
    return resolved_mime, width, height, checksum


def sanitize_filename(raw_name: str, *, fallback_ext: str = "jpg") -> str:
    base = Path(raw_name).name
    cleaned = re.sub(r"[^A-Za-z0-9._\-]", "_", base).strip("._")
    if not cleaned:
        return f"media.{fallback_ext}"
    return cleaned[:200]


class MediaAssetProcessor:
    """SSRF-safe featured media handler supporting url_only and local validated storage."""

    def __init__(
        self,
        *,
        settings: Settings,
        fetcher: SafeHttpFetcher,
        media_repo: MediaRepositoryProtocol,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher
        self.media_repo = media_repo

    def process_featured_image(
        self,
        *,
        source_url: str,
        brand_id: int | None,
        alt_text: str | None = None,
        storage_mode: str | None = None,
    ) -> MediaAsset | None:
        clean_url = source_url.strip()
        if not clean_url:
            return None

        # Always run SSRF check on every image URL even in url_only mode.
        validate_outbound_url(
            clean_url,
            trusted_internal_hosts=self.settings.trusted_internal_host_set,
            resolver=self.fetcher.resolver,
        )

        existing_by_url = self.media_repo.get_by_source_url(clean_url, brand_id=brand_id)
        mode = (storage_mode or self.settings.media_storage_mode).strip().lower()

        if mode == "url_only":
            if existing_by_url is not None:
                return existing_by_url
            parsed = urlparse(clean_url)
            file_name = sanitize_filename(Path(parsed.path).name or "featured-image.jpg")
            url_checksum = hashlib.sha256(clean_url.encode("utf-8")).hexdigest()
            return self.media_repo.create(
                brand_id=brand_id,
                file_name=file_name,
                file_path=None,
                source_url=clean_url[:1000],
                mime_type=None,
                file_size=None,
                width=None,
                height=None,
                alt_text=alt_text[:255] if alt_text else None,
                checksum=url_checksum,
            )

        # Local validated download & cache mode
        try:
            response = self.fetcher.fetch(
                clean_url,
                accept="image/jpeg,image/png,image/webp,image/gif,*/*;q=0.5",
                max_bytes=self.settings.media_max_file_bytes,
                timeout_seconds=self.settings.media_download_timeout_seconds,
                max_retries=1,
            )
        except ScannerError as exc:
            raise MediaValidationError(f"Failed to download image: {exc}") from exc

        if response.status_code != 200:
            raise MediaValidationError(f"Image download returned HTTP {response.status_code}.")

        mime_type, width, height, checksum = validate_image_bytes(
            response.content,
            max_file_bytes=self.settings.media_max_file_bytes,
            max_dimension_px=self.settings.media_max_dimension_px,
            declared_mime=response.headers.get("content-type"),
        )

        existing_by_checksum = self.media_repo.get_by_checksum(checksum)
        if existing_by_checksum is not None:
            return existing_by_checksum

        ext = ALLOWED_IMAGE_MIMES[mime_type]
        safe_name = f"{checksum[:24]}.{ext}"
        images_dir = self.settings.resolved_storage_root / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        dest_file = (images_dir / safe_name).resolve()
        if not str(dest_file).startswith(str(images_dir.resolve())):
            raise MediaValidationError("Resolved image storage path escaped storage root.")

        dest_file.write_bytes(response.content)
        relative_path = f"images/{safe_name}"

        return self.media_repo.create(
            brand_id=brand_id,
            file_name=safe_name,
            file_path=relative_path,
            source_url=clean_url[:1000],
            mime_type=mime_type,
            file_size=len(response.content),
            width=width,
            height=height,
            alt_text=alt_text[:255] if alt_text else None,
            checksum=checksum,
        )
