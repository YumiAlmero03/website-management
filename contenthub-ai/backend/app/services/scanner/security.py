from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.config import Settings
from app.services.scanner.exceptions import (
    ResponseTooLargeError,
    ScannerError,
    SSRFBlockedError,
)

ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})
ALLOWED_PUBLIC_PORTS: frozenset[int] = frozenset({80, 443})
BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata",
        "instance-data",
    }
)
BLOCKED_SUFFIXES: tuple[str, ...] = (".localhost", ".local", ".internal", ".home.arpa")
CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
CLOUD_METADATA_IPS: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "100.100.100.200",
        "fd00:ec2::254",
    }
)

DNSResolver = Callable[[str, int], list[str]]


def default_dns_resolver(hostname: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and isinstance(sockaddr[0], str) and sockaddr[0] not in ips:
            ips.append(sockaddr[0])
    return ips


def _is_unsafe_ip(raw_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return True

    if str(ip).lower() in CLOUD_METADATA_IPS:
        return True

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_unsafe_ip(str(ip.ipv4_mapped))

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True

    return isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT_NETWORK


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    scheme: str
    hostname: str
    port: int
    resolved_ips: tuple[str, ...]
    is_trusted_internal: bool


def validate_outbound_url(
    url: str,
    *,
    trusted_internal_hosts: set[str] | frozenset[str] | None = None,
    resolver: DNSResolver | None = None,
    resolve_dns: bool = True,
) -> ValidatedTarget:
    """Validate an outbound URL against SSRF, credential smuggling, port, and DNS policies."""
    raw = url.strip()
    if not raw or len(raw) > 2048:
        raise SSRFBlockedError("Outbound URL is empty or exceeds maximum length.")

    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFBlockedError(f"Blocked unsafe URL scheme: '{scheme or 'missing'}'.")

    if parsed.username is not None or parsed.password is not None:
        raise SSRFBlockedError("Embedded URL credentials are not permitted.")

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise SSRFBlockedError("Outbound URL must include a valid hostname.")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise SSRFBlockedError("Outbound URL contains an invalid port.") from exc

    trusted_hosts = {h.strip().lower() for h in (trusted_internal_hosts or set()) if h.strip()}
    is_trusted = hostname in trusted_hosts

    if not is_trusted:
        if port not in ALLOWED_PUBLIC_PORTS:
            raise SSRFBlockedError(f"Blocked unauthorized outbound port: {port}.")
        if hostname in BLOCKED_HOSTNAMES or any(hostname.endswith(s) for s in BLOCKED_SUFFIXES):
            raise SSRFBlockedError(f"Blocked internal or metadata hostname: '{hostname}'.")

    # Direct IP literal check before DNS lookup.
    try:
        ip_literal = ipaddress.ip_address(hostname)
    except ValueError:
        ip_literal = None

    if ip_literal is not None:
        resolved = [str(ip_literal)]
    elif not resolve_dns:
        resolved = []
    else:
        resolve_fn = resolver or default_dns_resolver
        try:
            resolved = resolve_fn(hostname, port)
        except OSError as exc:
            raise SSRFBlockedError(f"DNS resolution failed for '{hostname}'.") from exc

    if resolve_dns and not resolved:
        raise SSRFBlockedError(f"No network addresses resolved for '{hostname}'.")

    if not is_trusted:
        for ip_str in resolved:
            if _is_unsafe_ip(ip_str):
                raise SSRFBlockedError(
                    f"Blocked unsafe resolved IP address ({ip_str}) for hostname '{hostname}'."
                )

    return ValidatedTarget(
        url=raw,
        scheme=scheme,
        hostname=hostname,
        port=port,
        resolved_ips=tuple(resolved),
        is_trusted_internal=is_trusted,
    )


@dataclass(frozen=True)
class FetchedResponse:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None

    @property
    def text(self) -> str:
        content_type = self.headers.get("content-type", "")
        encoding = "utf-8"
        if "charset=" in content_type.lower():
            candidate = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip()
            if candidate:
                encoding = candidate
        try:
            return self.content.decode(encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


def _build_pinned_url(
    original_url: str, target: ValidatedTarget
) -> tuple[str, dict[str, str], dict[str, object]]:
    """Pin the TCP destination to the validated IP while preserving Host and TLS SNI."""
    parsed = urlparse(original_url)
    pinned_ip = target.resolved_ips[0]
    ip_host = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    default_port = 443 if target.scheme == "https" else 80
    netloc = ip_host if target.port == default_port else f"{ip_host}:{target.port}"
    pinned_url = urlunparse(
        (target.scheme, netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )
    host_header = (
        target.hostname if target.port == default_port else f"{target.hostname}:{target.port}"
    )
    extensions: dict[str, object] = {}
    if target.scheme == "https":
        extensions["sni_hostname"] = target.hostname.encode("ascii", errors="ignore")
    return pinned_url, {"Host": host_header}, extensions


class SafeHttpFetcher:
    """SSRF-protected, size-limited, redirect-validating HTTP client for website scanning."""

    def __init__(
        self,
        *,
        settings: Settings,
        resolver: DNSResolver | None = None,
        transport: httpx.BaseTransport | None = None,
        pin_resolved_ip: bool | None = None,
    ) -> None:
        self.settings = settings
        self.resolver = resolver
        self.transport = transport
        # Pin IP on live network requests to block DNS rebinding; skip pinning on mock transports.
        self.pin_resolved_ip = (transport is None) if pin_resolved_ip is None else pin_resolved_ip

    def _create_client(self, timeout_seconds: float) -> httpx.Client:
        return httpx.Client(
            transport=self.transport,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": self.settings.scanner_user_agent},
        )

    def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        accept: str | None = None,
        max_bytes: int | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> FetchedResponse:
        byte_limit = max_bytes or self.settings.scanner_max_response_bytes
        timeout = timeout_seconds or self.settings.scanner_request_timeout_seconds
        retries = self.settings.scanner_max_retries if max_retries is None else max_retries

        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return self._fetch_once(
                    url=url,
                    etag=etag,
                    last_modified=last_modified,
                    accept=accept,
                    max_bytes=byte_limit,
                    timeout_seconds=timeout,
                )
            except (SSRFBlockedError, ResponseTooLargeError):
                raise
            except (httpx.TimeoutException, httpx.TransportError, ScannerError) as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(min(2.0, 0.25 * (2**attempt)))
                    continue
                raise ScannerError(f"Outbound HTTP request failed for {url}: {exc}") from exc

        raise ScannerError(f"Outbound HTTP request failed for {url}: {last_exc}")

    def _fetch_once(
        self,
        *,
        url: str,
        etag: str | None,
        last_modified: str | None,
        accept: str | None,
        max_bytes: int,
        timeout_seconds: float,
    ) -> FetchedResponse:
        current_url = url
        redirects_remaining = self.settings.scanner_max_redirects

        with self._create_client(timeout_seconds) as client:
            while True:
                target = validate_outbound_url(
                    current_url,
                    trusted_internal_hosts=self.settings.trusted_internal_host_set,
                    resolver=self.resolver,
                )

                headers: dict[str, str] = {"User-Agent": self.settings.scanner_user_agent}
                if accept:
                    headers["Accept"] = accept
                if current_url == url:
                    if etag:
                        headers["If-None-Match"] = etag
                    if last_modified:
                        headers["If-Modified-Since"] = last_modified

                request_url = current_url
                extensions: dict[str, object] = {}
                if self.pin_resolved_ip:
                    request_url, host_headers, extensions = _build_pinned_url(current_url, target)
                    headers.update(host_headers)

                with client.stream(
                    "GET",
                    request_url,
                    headers=headers,
                    extensions=extensions or None,
                ) as response:
                    norm_headers = {k.lower(): v for k, v in response.headers.items()}

                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = norm_headers.get("location")
                        if not location:
                            raise ScannerError(
                                f"Redirect without Location header from {current_url}."
                            )
                        if redirects_remaining <= 0:
                            raise ScannerError(
                                "Exceeded maximum redirects "
                                f"({self.settings.scanner_max_redirects})."
                            )
                        redirects_remaining -= 1
                        current_url = urljoin(current_url, location.strip())
                        continue

                    if response.status_code == 304:
                        return FetchedResponse(
                            url=url,
                            final_url=current_url,
                            status_code=304,
                            headers=norm_headers,
                            content=b"",
                            not_modified=True,
                            etag=norm_headers.get("etag") or etag,
                            last_modified=norm_headers.get("last-modified") or last_modified,
                        )

                    content_length_raw = norm_headers.get("content-length")
                    if (
                        content_length_raw
                        and content_length_raw.isdigit()
                        and int(content_length_raw) > max_bytes
                    ):
                        raise ResponseTooLargeError(
                            f"Response Content-Length ({content_length_raw} bytes) "
                            f"exceeds limit ({max_bytes})."
                        )

                    chunks: list[bytes] = []
                    total_bytes = 0
                    for chunk in response.iter_bytes(chunk_size=16384):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise ResponseTooLargeError(
                                f"Response body exceeded maximum allowed size ({max_bytes} bytes)."
                            )
                        chunks.append(chunk)

                    if response.status_code >= 500:
                        raise ScannerError(f"Upstream server returned HTTP {response.status_code}.")

                    return FetchedResponse(
                        url=url,
                        final_url=current_url,
                        status_code=response.status_code,
                        headers=norm_headers,
                        content=b"".join(chunks),
                        not_modified=False,
                        etag=norm_headers.get("etag"),
                        last_modified=norm_headers.get("last-modified"),
                    )
