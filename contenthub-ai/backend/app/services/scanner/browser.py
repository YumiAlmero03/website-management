from __future__ import annotations

import threading

from app.config import Settings
from app.services.scanner.exceptions import BrowserUnavailableError
from app.services.scanner.security import DNSResolver, validate_outbound_url

_BROWSER_SEMAPHORE = threading.Semaphore(1)


class PlaywrightFallbackAdapter:
    """Optional browser rendering fallback (disabled by default, max 1 concurrent instance).

    Never attempts to bypass CAPTCHAs, Cloudflare challenges, or authentication gates.
    """

    method_name = "playwright"

    def __init__(
        self,
        *,
        settings: Settings,
        resolver: DNSResolver | None = None,
    ) -> None:
        self.settings = settings
        self.resolver = resolver

    def is_available(self) -> bool:
        if not self.settings.scanner_enable_playwright:
            return False
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False
        return True

    def render_html(self, url: str) -> str:
        if not self.settings.scanner_enable_playwright:
            raise BrowserUnavailableError(
                "Playwright browser fallback is disabled "
                "(set SCANNER_ENABLE_PLAYWRIGHT=true to enable)."
            )

        validate_outbound_url(
            url,
            trusted_internal_hosts=self.settings.trusted_internal_host_set,
            resolver=self.resolver,
        )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Playwright is not installed. "
                "Install the optional playwright package to use browser fallback."
            ) from exc

        acquired = _BROWSER_SEMAPHORE.acquire(timeout=10)
        if not acquired:
            raise BrowserUnavailableError("Browser concurrency limit (1) is currently busy.")

        try:
            timeout_ms = int(self.settings.scanner_request_timeout_seconds * 1000)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(user_agent=self.settings.scanner_user_agent)
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    return page.content()
                finally:
                    browser.close()
        finally:
            _BROWSER_SEMAPHORE.release()
