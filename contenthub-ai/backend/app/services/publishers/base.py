from __future__ import annotations

import base64
import hashlib
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.logging import redact_text
from app.services.publishers.exceptions import PublisherError, VerificationRequiredError


@dataclass(frozen=True)
class PublisherCapabilities:
    platform_key: str
    display_name: str
    priority_tier: int
    supports_official_api: bool
    supports_manual_fallback: bool = True
    supports_oauth: bool = False
    supports_pkce: bool = False
    supports_refresh: bool = False
    supports_target_selection: bool = False
    supports_text_post: bool = True
    supports_link_post: bool = True
    supports_image_post: bool = True
    supports_native_schedule: bool = False
    supports_reconcile: bool = False
    requires_media: bool = False
    requires_external_media_url: bool = False
    requires_paid_api_ack: bool = False
    required_scopes: tuple[str, ...] = ()
    api_version: str = "v1"
    limitations_summary: str = ""
    rate_limit_summary: str = ""


@dataclass(frozen=True)
class TargetResourceOption:
    target_id: str
    name: str
    account_type: str
    profile_url: str | None = None
    access_token_override: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OAuthStartResult:
    authorization_url: str
    state: str
    code_verifier: str | None = None
    requested_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OAuthCallbackResult:
    access_token: str
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    granted_scopes: list[str] = field(default_factory=list)
    external_account_id: str | None = None
    external_username: str | None = None
    external_display_name: str | None = None
    profile_url: str | None = None
    account_type: str | None = None
    target_resource_id: str | None = None
    target_resource_name: str | None = None
    available_targets: list[TargetResourceOption] = field(default_factory=list)
    access_tier: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OAuthTokenRefreshResult:
    access_token: str
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    granted_scopes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AccountVerifyResult:
    connected: bool
    connection_status: str
    eligibility_status: str
    eligibility_notes: str | None = None
    account_type: str | None = None
    external_account_id: str | None = None
    external_username: str | None = None
    external_display_name: str | None = None
    profile_url: str | None = None
    target_resource_id: str | None = None
    target_resource_name: str | None = None
    available_targets: list[TargetResourceOption] = field(default_factory=list)
    granted_scopes: list[str] = field(default_factory=list)
    missing_scopes: list[str] = field(default_factory=list)
    access_tier: str | None = None
    token_expires_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishMediaInput:
    media_asset_id: int
    file_path: str | None
    source_url: str | None
    public_url: str | None
    mime_type: str | None
    width: int | None
    height: int | None
    alt_text: str | None


@dataclass(frozen=True)
class PublishRequest:
    social_post_id: int
    social_profile_id: int
    website_id: int
    platform_key: str
    idempotency_key: str
    title: str | None
    caption: str
    assembled_content: str
    source_url: str | None
    cta_text: str | None
    target_resource_id: str | None
    external_account_id: str | None
    scheduled_for_utc: datetime | None
    credentials: dict[str, str | None]
    media: list[PublishMediaInput] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishResult:
    external_post_id: str | None
    published_url: str | None
    http_status: int | None
    verification_status: str
    response_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconcileResult:
    exists: bool
    indeterminate: bool = False
    external_post_id: str | None = None
    published_url: str | None = None
    note: str | None = None


def generate_pkce_pair() -> tuple[str, str]:
    """Generate RFC 7636 S256 (code_verifier, code_challenge)."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class TrustedPublisherHttpClient:
    """HTTPX client restricted to an explicit allowlist of official API hostnames."""

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def _validate_target_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in self.allowed_hosts:
            raise PublisherError(
                f"Blocked outbound publishing URL host '{host or 'unknown'}'.",
                error_category="policy_restriction",
                code="UNTRUSTED_PROVIDER_HOST",
            )
        return url

    def request(
        self,
        method: str,
        url: str,
        *,
        is_publish_mutation: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        safe_url = self._validate_target_url(url)
        timeout = kwargs.pop("timeout", self.timeout_seconds)
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                return client.request(method, safe_url, **kwargs)
        except httpx.TimeoutException as exc:
            if is_publish_mutation:
                raise VerificationRequiredError(
                    "Publishing request timed out after submission; verify post before retry.",
                    code="PUBLISH_TIMEOUT_AMBIGUOUS",
                ) from exc
            raise PublisherError(
                "Upstream platform request timed out.",
                error_category="network_error",
                code="PROVIDER_TIMEOUT",
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            if is_publish_mutation:
                raise VerificationRequiredError(
                    "Network interrupted while publishing; verify external status before retry.",
                    code="PUBLISH_TRANSPORT_AMBIGUOUS",
                ) from exc
            raise PublisherError(
                f"Network error contacting platform API: {redact_text(str(exc))}",
                error_category="network_error",
                code="PROVIDER_NETWORK_ERROR",
                retryable=True,
            ) from exc


def parse_retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(1, min(3600, int(raw.strip())))
    except ValueError:
        return None


def classify_http_failure(
    response: httpx.Response,
    *,
    is_publish_mutation: bool = False,
) -> PublisherError:
    status = response.status_code
    retry_after = parse_retry_after(response)
    try:
        body_json = response.json()
        err_obj = body_json.get("error") if isinstance(body_json, dict) else None
        raw_msg = ""
        if isinstance(err_obj, dict):
            raw_msg = str(err_obj.get("message") or body_json.get("message") or "")
        elif isinstance(body_json, dict):
            raw_msg = str(
                body_json.get("error_description")
                or body_json.get("message")
                or body_json.get("detail")
                or response.text[:250]
            )
        else:
            raw_msg = response.text[:250]
    except Exception:
        raw_msg = response.text[:250]

    msg = redact_text(raw_msg or f"HTTP {status} from upstream platform")
    if status == 401:
        return PublisherError(
            msg,
            error_category="expired_credentials",
            code="HTTP_401_UNAUTHORIZED",
            http_status=status,
        )
    if status == 403:
        lower = msg.lower()
        if "quota" in lower or "approval" in lower or "policy" in lower or "eligible" in lower:
            return PublisherError(
                msg,
                error_category="policy_restriction",
                code="HTTP_403_RESTRICTED",
                http_status=status,
            )
        return PublisherError(
            msg,
            error_category="missing_permissions",
            code="HTTP_403_FORBIDDEN",
            http_status=status,
        )
    if status == 429:
        return PublisherError(
            msg,
            error_category="rate_limited",
            code="HTTP_429_RATE_LIMITED",
            http_status=status,
            retryable=True,
            retry_after_seconds=retry_after or 120,
        )
    if status in (400, 422):
        lower = msg.lower()
        category = (
            "invalid_media"
            if any(k in lower for k in ("image", "media", "aspect", "photo", "resolution"))
            else "rejected_content"
        )
        return PublisherError(
            msg,
            error_category=category,
            code=f"HTTP_{status}_REJECTED",
            http_status=status,
        )
    if status >= 500:
        if is_publish_mutation:
            return VerificationRequiredError(
                f"Provider returned ambiguous HTTP {status}; verify before retrying: {msg}",
                code=f"HTTP_{status}_AMBIGUOUS",
                http_status=status,
            )
        return PublisherError(
            msg,
            error_category="provider_outage",
            code=f"HTTP_{status}_OUTAGE",
            http_status=status,
            retryable=True,
        )
    return PublisherError(
        msg,
        error_category="rejected_content",
        code=f"HTTP_{status}_ERROR",
        http_status=status,
    )


class BasePublisherAdapter(ABC):
    """Abstract contract for official publishing adapters and manual fallback."""

    capabilities: PublisherCapabilities
    allowed_hosts: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        api_version: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.api_version = api_version or self.capabilities.api_version
        self.http = TrustedPublisherHttpClient(
            allowed_hosts=self.allowed_hosts,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    @abstractmethod
    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        """Raise PublisherError if required API credential fields are missing or malformed."""

    @abstractmethod
    def verify_connection(
        self,
        *,
        credentials: dict[str, str | None],
        external_account_id: str | None = None,
        target_resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AccountVerifyResult:
        """Verify token validity, account type/eligibility, targets, and granted scopes."""

    @abstractmethod
    def publish_post(self, request: PublishRequest) -> PublishResult:
        """Execute post publication using official APIs only."""

    def build_oauth_authorize_url(
        self,
        *,
        credentials: dict[str, str | None],
        redirect_uri: str,
        state: str,
        scopes: list[str] | None = None,
    ) -> OAuthStartResult:
        raise PublisherError(
            f"{self.capabilities.display_name} does not support automated OAuth flow.",
            error_category="unsupported_account",
            code="OAUTH_UNSUPPORTED",
        )

    def exchange_oauth_code(
        self,
        *,
        credentials: dict[str, str | None],
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> OAuthCallbackResult:
        raise PublisherError(
            f"{self.capabilities.display_name} does not support automated OAuth callback exchange.",
            error_category="unsupported_account",
            code="OAUTH_UNSUPPORTED",
        )

    def refresh_credentials(
        self, *, credentials: dict[str, str | None]
    ) -> OAuthTokenRefreshResult:
        raise PublisherError(
            f"{self.capabilities.display_name} does not support automated token refresh.",
            error_category="expired_credentials",
            code="REFRESH_UNSUPPORTED",
        )

    def reconcile_publication(
        self,
        *,
        request: PublishRequest,
        external_post_id: str | None = None,
    ) -> ReconcileResult:
        return ReconcileResult(
            exists=False,
            indeterminate=True,
            note="Automatic reconciliation is unavailable for this platform; verify manually.",
        )

    def get_publication_status(
        self,
        *,
        credentials: dict[str, str | None],
        external_post_id: str,
    ) -> ReconcileResult:
        return ReconcileResult(exists=False, indeterminate=True)
