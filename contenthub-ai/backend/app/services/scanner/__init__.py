from app.services.scanner.base import DiscoveredCandidate, DiscoveryResult
from app.services.scanner.discovery import WebsiteAutoDiscovery
from app.services.scanner.exceptions import (
    BrowserUnavailableError,
    DiscoveryError,
    ResponseTooLargeError,
    RobotsDisallowedError,
    ScannerError,
    SSRFBlockedError,
)
from app.services.scanner.manager import WebsiteDiscoveryManager
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.security import SafeHttpFetcher, validate_outbound_url
from app.services.scanner.url_normalizer import (
    hash_url,
    is_same_site,
    matches_url_patterns,
    normalize_domain,
    normalize_url,
    validate_url_patterns,
)

__all__ = [
    "BrowserUnavailableError",
    "DiscoveredCandidate",
    "DiscoveryError",
    "DiscoveryResult",
    "ResponseTooLargeError",
    "RobotsDisallowedError",
    "RobotsPolicyChecker",
    "SSRFBlockedError",
    "SafeHttpFetcher",
    "ScannerError",
    "WebsiteAutoDiscovery",
    "WebsiteDiscoveryManager",
    "hash_url",
    "is_same_site",
    "matches_url_patterns",
    "normalize_domain",
    "normalize_url",
    "validate_outbound_url",
    "validate_url_patterns",
]
