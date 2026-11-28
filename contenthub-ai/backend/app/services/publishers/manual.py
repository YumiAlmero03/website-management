from __future__ import annotations

from typing import Any

from app.services.publishers.base import (
    AccountVerifyResult,
    BasePublisherAdapter,
    PublisherCapabilities,
    PublishRequest,
    PublishResult,
)


class ManualPublisherAdapter(BasePublisherAdapter):
    """First-class Manual Publishing adapter requiring zero API credentials."""

    capabilities = PublisherCapabilities(
        platform_key="custom_social",
        display_name="Manual / Custom Platform",
        priority_tier=1,
        supports_official_api=False,
        supports_manual_fallback=True,
        supports_oauth=False,
        supports_pkce=False,
        supports_refresh=False,
        supports_target_selection=False,
        supports_text_post=True,
        supports_link_post=True,
        supports_image_post=True,
        supports_native_schedule=False,
        supports_reconcile=False,
        requires_media=False,
        requires_external_media_url=False,
        requires_paid_api_ack=False,
        api_version="manual",
        limitations_summary="Manual copy/export workflow with administrator URL recording.",
        rate_limit_summary="No external API limit.",
    )

    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        # Manual publishing never requires API credentials.
        return None

    def verify_connection(
        self,
        *,
        credentials: dict[str, str | None],
        external_account_id: str | None = None,
        target_resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AccountVerifyResult:
        return AccountVerifyResult(
            connected=True,
            connection_status="configured",
            eligibility_status="manual_only",
            eligibility_notes=(
                "Manual publishing workflow active; copy formatted caption and record live URL."
            ),
            account_type="manual",
            external_account_id=external_account_id,
            access_tier="manual",
        )

    def publish_post(self, request: PublishRequest) -> PublishResult:
        # Automated API calls do not execute in manual mode; mark-published records outcome.
        return PublishResult(
            external_post_id=None,
            published_url=None,
            http_status=None,
            verification_status="self_reported",
            response_summary={"mode": "manual", "note": "Ready for manual publication."},
        )
