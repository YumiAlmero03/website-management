from __future__ import annotations


class ScannerError(Exception):
    """Base exception for website scanning and outbound HTTP operations."""


class SSRFBlockedError(ScannerError):
    """Raised when an outbound URL violates SSRF network/scheme/port policies."""


class ResponseTooLargeError(ScannerError):
    """Raised when an outbound HTTP response or decompressed payload exceeds configured limits."""


class RobotsDisallowedError(ScannerError):
    """Raised when robots.txt forbids fetching a target URL."""


class DiscoveryError(ScannerError):
    """Raised when a discovery adapter fails to parse or reach its target."""


class BrowserUnavailableError(ScannerError):
    """Raised when optional Playwright rendering is disabled or not installed."""
