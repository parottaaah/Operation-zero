"""SSRF protection for user-supplied health-check URLs.

Controls:
* Only ``http``/``https``.
* Reject embedded credentials, empty hosts, unusual ports.
* Resolve every A/AAAA record and reject loopback, private, link-local, reserved,
  multicast and unspecified addresses (IPv4 and IPv6, including mapped forms).
* Block known cloud metadata hostnames and ``.local``/``.internal`` suffixes.
* Redirects are followed manually (bounded) and each hop is re-validated.
* Re-resolve after the request to detect DNS rebinding; a mismatch fails closed.
* Optional per-workspace hostname allowlist for private-network checks that an
  administrator explicitly enabled.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.errors import SsrfBlocked

logger = logging.getLogger(__name__)

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "169.254.169.254",
    "fd00:ec2::254",
}
BLOCKED_SUFFIXES = (".local", ".internal", ".localdomain", ".home.arpa")
ALLOWED_SCHEMES = {"http", "https"}
MAX_RESPONSE_BYTES = 65_536


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    host: str
    port: int
    resolved_ips: tuple[str, ...]


def _is_public_ip(raw_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if isinstance(ip, ipaddress.IPv6Address) and ip.sixtofour is not None:
        return ipaddress.ip_address(ip.sixtofour).is_global
    return bool(ip.is_global) and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_host(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SsrfBlocked("health-check host cannot be resolved") from exc
    ips = tuple(sorted({info[4][0] for info in infos}))
    if not ips:
        raise SsrfBlocked("health-check host resolved to no addresses")
    return ips


def validate_url(url: str, *, allow_private: bool | None = None) -> ValidatedTarget:
    """Validate a health-check URL and return the resolved target.

    Raises ``SsrfBlocked`` when the target is not permitted.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SsrfBlocked("health-check URL must use http or https")
    if parsed.username or parsed.password:
        raise SsrfBlocked("health-check URL must not contain credentials")
    if not parsed.hostname:
        raise SsrfBlocked("health-check URL is missing a hostname")
    if parsed.fragment:
        raise SsrfBlocked("health-check URL must not contain a fragment")

    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    if port not in (80, 443) and port < 1024:
        raise SsrfBlocked("health-check port is not permitted")

    if host in BLOCKED_HOSTNAMES or any(host.endswith(suffix) for suffix in BLOCKED_SUFFIXES):
        raise SsrfBlocked("health-check hostname is on the blocked list")

    private_allowed = settings.allow_private_health_checks if allow_private is None else allow_private
    allowlist = {h.lower() for h in settings.healthcheck_allowed_hosts}

    if private_allowed and allowlist and host not in allowlist:
        raise SsrfBlocked(
            "private health checks are enabled but this host is not in OZ_HEALTHCHECK_ALLOWED_HOSTS"
        )

    try:
        literal_ip = ipaddress.ip_address(host)
        ips: tuple[str, ...] = (str(literal_ip),)
    except ValueError:
        ips = resolve_host(host, port)

    if not private_allowed:
        for ip in ips:
            if not _is_public_ip(ip):
                raise SsrfBlocked("health-check target resolves to a private or reserved address")

    return ValidatedTarget(url=url.strip(), host=host, port=port, resolved_ips=ips)


def validate_redirect(origin: ValidatedTarget, location: str) -> ValidatedTarget:
    from urllib.parse import urljoin

    next_url = urljoin(origin.url, location)
    return validate_url(next_url)


@dataclass
class FetchOutcome:
    status_code: int | None
    latency_ms: float
    error_kind: str = ""
    error_message: str = ""
    final_url: str = ""
    redirects: int = 0


async def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    timeout_seconds: int = 5,
    allow_private: bool | None = None,
    client: httpx.AsyncClient | None = None,
) -> FetchOutcome:
    """Perform a bounded, SSRF-validated HTTP request.

    The response body is read with a hard cap and discarded; only status, latency
    and a bounded error description are returned.
    """
    import time

    started = time.perf_counter()
    target = validate_url(url, allow_private=allow_private)
    own_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        headers={"User-Agent": "OperationZero-HealthChecker/1.0"},
    )
    redirects = 0
    try:
        current = target
        while True:
            try:
                response = await client.request(method.upper(), current.url)
            except httpx.TimeoutException:
                return FetchOutcome(
                    status_code=None,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_kind="timeout",
                    error_message="request timed out",
                    final_url=current.url,
                    redirects=redirects,
                )
            except httpx.HTTPError as exc:
                return FetchOutcome(
                    status_code=None,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_kind="connection_error",
                    error_message=type(exc).__name__,
                    final_url=current.url,
                    redirects=redirects,
                )

            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                redirects += 1
                if redirects > settings.max_healthcheck_redirects:
                    return FetchOutcome(
                        status_code=response.status_code,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        error_kind="too_many_redirects",
                        error_message="redirect limit exceeded",
                        final_url=current.url,
                        redirects=redirects,
                    )
                try:
                    current = validate_redirect(current, response.headers["location"])
                except SsrfBlocked:
                    return FetchOutcome(
                        status_code=None,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        error_kind="blocked_redirect",
                        error_message="redirect target blocked by SSRF policy",
                        final_url=current.url,
                        redirects=redirects,
                    )
                continue

            # Drain at most MAX_RESPONSE_BYTES so a huge body cannot exhaust memory.
            try:
                body = await response.aread()
                body = body[:MAX_RESPONSE_BYTES]
                del body
            except httpx.HTTPError:
                pass

            # Re-resolve to detect DNS rebinding between validation and response.
            try:
                post_ips = resolve_host(current.host, current.port)
            except SsrfBlocked:
                post_ips = current.resolved_ips
            private_allowed = (
                allow_private if allow_private is not None else settings.allow_private_health_checks
            )
            if not private_allowed and any(ip not in current.resolved_ips for ip in post_ips):
                return FetchOutcome(
                    status_code=None,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_kind="dns_rebinding",
                    error_message="host resolution changed during the request",
                    final_url=current.url,
                    redirects=redirects,
                )

            return FetchOutcome(
                status_code=response.status_code,
                latency_ms=(time.perf_counter() - started) * 1000,
                final_url=str(response.url),
                redirects=redirects,
            )
    finally:
        if own_client:
            await client.aclose()
