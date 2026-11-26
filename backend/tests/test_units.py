"""Unit tests for redaction, SSRF validation and safe fetch behaviour."""

from __future__ import annotations

import httpx
import pytest

from app.services import ssrf
from app.services.redaction import MASK, RedactionReport, redact, redact_value


@pytest.fixture()
def public_resolution(monkeypatch):
    monkeypatch.setattr(ssrf, "resolve_host", lambda host, port: ("93.184.216.34",))
    monkeypatch.setattr(ssrf.settings, "allow_private_health_checks", False)


def test_redaction_masks_known_secret_shapes():
    message, attributes, report = redact(
        "auth=Bearer abcdefghijklmnopqrstuvwxyz123456 password=letmein123 "
        "key sk-abcdefghijklmnopqrstuvwxyz ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        {
            "Authorization": "Bearer xyz",
            "nested": {"client_secret": "shhh", "safe": "keep"},
            "email": "person@example.com",
            "url": "postgresql://u:pa55w0rd@db:5432/app",
        },
    )
    assert "letmein123" not in message
    assert "abcdefghijklmnopqrstuvwxyz123456" not in message
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in message
    assert "ghp_aaaaaaaa" not in message
    assert attributes["Authorization"] == MASK
    assert attributes["nested"]["client_secret"] == MASK
    assert attributes["nested"]["safe"] == "keep"
    assert attributes["email"] == MASK
    assert "pa55w0rd" not in attributes["url"]
    assert report.count > 0
    assert report.fields


def test_redaction_handles_lists_tuples_and_bytes():
    report = RedactionReport()
    value = redact_value(
        {"items": [{"token": "abc"}, ("plain", b"bytes")], "count": 2},
        report,
        "attributes",
    )
    assert value["items"][0]["token"] == MASK
    assert value["items"][1] == ["plain", MASK]
    assert value["count"] == 2


def test_redaction_keeps_ordinary_telemetry():
    message, attributes, report = redact(
        "GET /checkout 200 in 82ms",
        {"order_id": "ord_123", "duration_ms": 82, "region": "ap-south-1"},
    )
    assert message == "GET /checkout 200 in 82ms"
    assert attributes == {"order_id": "ord_123", "duration_ms": 82, "region": "ap-south-1"}
    assert report.count == 0


def test_redaction_masks_card_numbers():
    message, _, report = redact("card 4111 1111 1111 1111 declined")
    assert "4111" not in message
    assert report.count == 1


@pytest.mark.asyncio
async def test_safe_fetch_success(public_resolution):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    outcome = await ssrf.safe_fetch("https://93.184.216.34/health", client=client)
    await client.aclose()
    assert outcome.status_code == 200
    assert outcome.error_kind == ""
    assert outcome.latency_ms >= 0


@pytest.mark.asyncio
async def test_safe_fetch_blocks_private_redirect(public_resolution):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1:9000/admin"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    outcome = await ssrf.safe_fetch("https://93.184.216.34/health", client=client)
    await client.aclose()
    assert outcome.error_kind == "blocked_redirect"
    assert outcome.status_code is None


@pytest.mark.asyncio
async def test_safe_fetch_blocks_redirect_loop(public_resolution):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://93.184.216.34/again"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    outcome = await ssrf.safe_fetch("https://93.184.216.34/health", client=client)
    await client.aclose()
    assert outcome.error_kind == "too_many_redirects"


@pytest.mark.asyncio
async def test_safe_fetch_timeout(public_resolution):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    outcome = await ssrf.safe_fetch("https://93.184.216.34/health", client=client)
    await client.aclose()
    assert outcome.error_kind == "timeout"


@pytest.mark.asyncio
async def test_safe_fetch_detects_dns_rebinding(public_resolution, monkeypatch):
    responses = iter([("93.184.216.34",), ("10.0.0.9",)])
    monkeypatch.setattr(ssrf, "resolve_host", lambda host, port: next(responses))

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    outcome = await ssrf.safe_fetch("https://rebind.example.com/health", client=client)
    await client.aclose()
    assert outcome.error_kind == "dns_rebinding"


def test_private_checks_require_explicit_allowlist(monkeypatch):
    monkeypatch.setattr(ssrf.settings, "allow_private_health_checks", True)
    monkeypatch.setattr(ssrf.settings, "healthcheck_allowed_hosts", ["internal.example.com"])
    monkeypatch.setattr(ssrf, "resolve_host", lambda host, port: ("10.0.0.5",))
    target = ssrf.validate_url("https://internal.example.com/health", allow_private=True)
    assert target.resolved_ips == ("10.0.0.5",)
    with pytest.raises(ssrf.SsrfBlocked):
        ssrf.validate_url("https://other.example.com/health", allow_private=True)


def test_ipv6_mapped_ipv4_private_is_blocked():
    for url in ["http://[::ffff:10.0.0.1]/", "http://[fd00::1]/"]:
        with pytest.raises(ssrf.SsrfBlocked):
            ssrf.validate_url(url)


def test_settings_accept_csv_and_json_list_env_values(monkeypatch):
    """`.env.example` documents CSV; a JSON array must keep working too."""
    from app.core.config import Settings

    monkeypatch.setenv("OZ_CORS_ORIGINS", "http://localhost:5173, http://localhost:3000")
    monkeypatch.setenv("OZ_TRUSTED_HOSTS", '["api.example.com","web.example.com"]')
    monkeypatch.setenv("OZ_HEALTHCHECK_ALLOWED_HOSTS", "")
    settings = Settings()

    assert settings.cors_origins == ["http://localhost:5173", "http://localhost:3000"]
    assert settings.trusted_hosts == ["api.example.com", "web.example.com"]
    assert settings.healthcheck_allowed_hosts == []
