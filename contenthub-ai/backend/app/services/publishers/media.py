from __future__ import annotations

import hashlib
import io
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.models.base import utc_now_naive
from app.models.media_asset import MediaAsset
from app.models.publishing import SocialPostMedia
from app.services.publishers.base import PublishMediaInput
from app.services.publishers.exceptions import PublisherError
from app.services.scanner.exceptions import ScannerError
from app.services.scanner.security import SafeHttpFetcher

PLATFORM_MEDIA_RULES: dict[str, dict[str, Any]] = {
    "instagram": {
        "formats": ("JPEG",),
        "target_format": "JPEG",
        "max_bytes": 8_388_608,
        "min_width": 320,
        "max_width": 1440,
        "min_aspect": 0.8,
        "max_aspect": 1.91,
    },
    "facebook": {
        "formats": ("JPEG", "PNG", "GIF"),
        "target_format": "JPEG",
        "max_bytes": 8_388_608,
        "min_width": 200,
        "max_width": 4096,
        "min_aspect": 0.4,
        "max_aspect": 2.5,
    },
    "threads": {
        "formats": ("JPEG", "PNG"),
        "target_format": "JPEG",
        "max_bytes": 8_388_608,
        "min_width": 200,
        "max_width": 1440,
        "min_aspect": 0.5,
        "max_aspect": 2.0,
    },
    "linkedin": {
        "formats": ("JPEG", "PNG", "GIF"),
        "target_format": "JPEG",
        "max_bytes": 8_388_608,
        "min_width": 200,
        "max_width": 4096,
        "min_aspect": 0.4,
        "max_aspect": 3.0,
    },
    "google_business_profile": {
        "formats": ("JPEG", "PNG"),
        "target_format": "JPEG",
        "max_bytes": 5_242_880,
        "min_width": 250,
        "max_width": 2048,
        "min_aspect": 0.5,
        "max_aspect": 2.0,
    },
    "pinterest": {
        "formats": ("JPEG", "PNG"),
        "target_format": "JPEG",
        "max_bytes": 10_485_760,
        "min_width": 200,
        "max_width": 4096,
        "min_aspect": 0.3,
        "max_aspect": 2.5,
    },
    "twitter": {
        "formats": ("JPEG", "PNG", "GIF"),
        "target_format": "JPEG",
        "max_bytes": 5_242_880,
        "min_width": 200,
        "max_width": 4096,
        "min_aspect": 0.3,
        "max_aspect": 3.0,
    },
    "custom_social": {
        "formats": ("JPEG", "PNG", "WEBP", "GIF"),
        "target_format": "JPEG",
        "max_bytes": 10_485_760,
        "min_width": 100,
        "max_width": 4096,
        "min_aspect": 0.2,
        "max_aspect": 4.0,
    },
}


def resolve_public_media_base_url(settings: Settings) -> str | None:
    candidate = (settings.public_media_base_url or "").strip().rstrip("/")
    if not candidate:
        candidate = (settings.app_url or "").strip().rstrip("/")
    if not candidate:
        return None
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}:
        return None
    return candidate


def _load_asset_bytes(
    *,
    settings: Settings,
    asset: MediaAsset,
    fetcher: SafeHttpFetcher | None,
) -> bytes:
    if asset.file_path:
        root = settings.resolved_storage_root.resolve()
        candidate = (root / asset.file_path).resolve()
        if not str(candidate).startswith(str(root)) or not candidate.is_file():
            raise PublisherError(
                f"Media file '{asset.file_name}' is missing or escaped storage root.",
                error_category="invalid_media",
                code="MEDIA_FILE_NOT_FOUND",
            )
        return candidate.read_bytes()

    if asset.source_url and fetcher is not None:
        try:
            resp = fetcher.fetch(
                asset.source_url,
                accept="image/jpeg,image/png,image/webp,image/gif,*/*;q=0.5",
                max_bytes=settings.media_max_file_bytes,
                timeout_seconds=settings.media_download_timeout_seconds,
                max_retries=1,
            )
            if resp.status_code == 200:
                return resp.content
        except ScannerError as exc:
            raise PublisherError(
                f"Failed to fetch remote media asset: {exc}",
                error_category="invalid_media",
                code="MEDIA_FETCH_FAILED",
            ) from exc
    raise PublisherError(
        f"Media asset #{asset.id} has neither a local file nor downloadable source URL.",
        error_category="invalid_media",
        code="MEDIA_UNAVAILABLE",
    )


def prepare_media_for_platform(
    *,
    settings: Settings,
    platform_key: str,
    post_id: int,
    attachment: SocialPostMedia,
    asset: MediaAsset,
    fetcher: SafeHttpFetcher | None = None,
    requires_external_url: bool = False,
) -> tuple[dict[str, Any], PublishMediaInput]:
    """Validate and convert/resize an attachment into STORAGE_ROOT/prepared_media/."""
    rules = PLATFORM_MEDIA_RULES.get(platform_key, PLATFORM_MEDIA_RULES["custom_social"])
    raw_bytes = _load_asset_bytes(settings=settings, asset=asset, fetcher=fetcher)
    Image.MAX_IMAGE_PIXELS = settings.media_max_dimension_px * settings.media_max_dimension_px

    try:
        with Image.open(io.BytesIO(raw_bytes)) as opened:
            opened = ImageOps.exif_transpose(opened)
            orig_fmt = (opened.format or "JPEG").upper()
            width, height = opened.size
            if width <= 0 or height <= 0:
                raise PublisherError(
                    "Attached image has zero dimensions.",
                    error_category="invalid_media",
                    code="MEDIA_ZERO_DIMENSIONS",
                )

            aspect = width / float(height)
            min_aspect = float(rules["min_aspect"])
            max_aspect = float(rules["max_aspect"])
            if aspect < min_aspect or aspect > max_aspect:
                # Center-crop to nearest compliant boundary when slightly off, else reject extreme
                if aspect < min_aspect * 0.55 or aspect > max_aspect * 1.8:
                    raise PublisherError(
                        f"Image aspect ratio ({width}x{height} = {aspect:.2f}) violates "
                        f"{platform_key} limits ({min_aspect:.2f} to {max_aspect:.2f}).",
                        error_category="invalid_media",
                        code="MEDIA_ASPECT_INVALID",
                    )
                if aspect < min_aspect:
                    target_h = int(width / min_aspect)
                    top = max(0, (height - target_h) // 2)
                    opened = opened.crop((0, top, width, top + target_h))
                elif aspect > max_aspect:
                    target_w = int(height * max_aspect)
                    left = max(0, (width - target_w) // 2)
                    opened = opened.crop((left, 0, left + target_w, height))
                width, height = opened.size

            min_w = int(rules["min_width"])
            max_w = int(rules["max_width"])
            if width < min_w:
                raise PublisherError(
                    f"Image width ({width}px) is below {platform_key} minimum ({min_w}px).",
                    error_category="invalid_media",
                    code="MEDIA_TOO_SMALL",
                )
            if width > max_w:
                scale = max_w / float(width)
                opened = opened.resize(
                    (max_w, max(1, int(height * scale))),
                    Image.Resampling.LANCZOS,
                )
                width, height = opened.size

            target_fmt = (
                orig_fmt
                if orig_fmt in rules["formats"]
                and len(raw_bytes) <= int(rules["max_bytes"])
                and width == asset.width
                else str(rules["target_format"])
            )
            out_buf = io.BytesIO()
            if target_fmt == "JPEG":
                rgb = opened.convert("RGB")
                rgb.save(out_buf, format="JPEG", quality=90, optimize=True)
                out_mime = "image/jpeg"
                ext = "jpg"
            elif target_fmt == "PNG":
                opened.save(out_buf, format="PNG", optimize=True)
                out_mime = "image/png"
                ext = "png"
            else:
                opened.save(out_buf, format=target_fmt)
                out_mime = f"image/{target_fmt.lower()}"
                ext = target_fmt.lower()
            out_bytes = out_buf.getvalue()
    except PublisherError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise PublisherError(
            f"Invalid image asset #{asset.id}: {exc}",
            error_category="invalid_media",
            code="MEDIA_CORRUPT",
        ) from exc

    if len(out_bytes) > int(rules["max_bytes"]):
        raise PublisherError(
            f"Prepared image ({len(out_bytes)} bytes) exceeds {platform_key} "
            f"limit ({rules['max_bytes']} bytes).",
            error_category="invalid_media",
            code="MEDIA_TOO_LARGE",
        )

    digest = hashlib.sha256(out_bytes).hexdigest()[:20]
    rel_dir = Path("prepared_media") / f"post_{post_id}"
    abs_dir = (settings.resolved_storage_root / rel_dir).resolve()
    root_resolved = settings.resolved_storage_root.resolve()
    if not str(abs_dir).startswith(str(root_resolved)):
        raise PublisherError(
            "Prepared media path escaped storage root.",
            error_category="invalid_media",
            code="MEDIA_PATH_INVALID",
        )
    abs_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{platform_key}_{attachment.id}_{digest}.{ext}"
    abs_path = (abs_dir / file_name).resolve()
    if not str(abs_path).startswith(str(abs_dir)):
        raise PublisherError(
            "Prepared media file escaped storage directory.",
            error_category="invalid_media",
            code="MEDIA_PATH_INVALID",
        )
    abs_path.write_bytes(out_bytes)
    rel_path = (rel_dir / file_name).as_posix()

    public_token = attachment.public_media_token or secrets.token_urlsafe(32)
    public_expires = utc_now_naive() + timedelta(hours=24)
    public_base = resolve_public_media_base_url(settings)
    public_url: str | None = None
    if public_base:
        public_url = f"{public_base}/api/v1/public-media/{public_token}"
    elif (
        asset.source_url
        and asset.source_url.startswith("https://")
        and target_fmt in rules["formats"]
    ):
        public_url = asset.source_url

    if requires_external_url and not public_url:
        raise PublisherError(
            f"{platform_key.title()} requires a publicly reachable HTTPS image URL. "
            "Configure PUBLIC_MEDIA_BASE_URL (or public HTTPS APP_URL) or attach an HTTPS image.",
            error_category="invalid_media",
            code="PUBLIC_MEDIA_URL_REQUIRED",
        )

    updates = {
        "is_prepared": True,
        "prepared_file_path": rel_path,
        "prepared_mime_type": out_mime,
        "prepared_width": width,
        "prepared_height": height,
        "prepared_file_size": len(out_bytes),
        "public_media_token": public_token,
        "public_media_expires_at": public_expires,
    }
    media_input = PublishMediaInput(
        media_asset_id=asset.id,
        file_path=rel_path,
        source_url=asset.source_url,
        public_url=public_url,
        mime_type=out_mime,
        width=width,
        height=height,
        alt_text=attachment.alt_text or asset.alt_text,
    )
    return updates, media_input
