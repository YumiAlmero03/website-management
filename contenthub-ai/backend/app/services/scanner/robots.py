from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from app.services.scanner.exceptions import ScannerError
from app.services.scanner.security import SafeHttpFetcher


class RobotsPolicyChecker:
    """Fetches and caches robots.txt rules per origin safely through SafeHttpFetcher."""

    def __init__(
        self,
        *,
        fetcher: SafeHttpFetcher,
        user_agent: str,
        respect_robots: bool = True,
    ) -> None:
        self.fetcher = fetcher
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self._cache: dict[str, tuple[RobotFileParser | None, list[str]]] = {}

    def _load(self, origin: str) -> tuple[RobotFileParser | None, list[str]]:
        if origin in self._cache:
            return self._cache[origin]

        robots_url = f"{origin}/robots.txt"
        sitemaps: list[str] = []
        try:
            response = self.fetcher.fetch(robots_url, accept="text/plain,*/*", max_retries=1)
        except ScannerError:
            self._cache[origin] = (None, [])
            return None, []

        if response.status_code != 200:
            self._cache[origin] = (None, [])
            return None, []

        lines = response.text.splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("sitemap:"):
                candidate = stripped.split(":", 1)[1].strip()
                if candidate and candidate not in sitemaps:
                    sitemaps.append(candidate)

        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(lines)
        self._cache[origin] = (parser, sitemaps)
        return parser, sitemaps

    def is_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser, _ = self._load(origin)
        if parser is None:
            return True
        return bool(parser.can_fetch(self.user_agent, url))

    def get_crawl_delay(self, url: str) -> float | None:
        if not self.respect_robots:
            return None
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser, _ = self._load(origin)
        if parser is None:
            return None
        delay = parser.crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None

    def get_sitemap_urls(self, origin: str) -> list[str]:
        _, sitemaps = self._load(origin.rstrip("/"))
        return list(sitemaps)
