"""Real-infrastructure integration tests.

These tests are skipped locally when the required service is absent. CI sets
``OZ_REQUIRE_REDIS_TESTS=1`` so a missing Redis service fails instead of skipping.
"""

from __future__ import annotations

import os
import uuid

import pytest
import redis

from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import reset_rate_limiter_state

pytestmark = pytest.mark.integration


def _redis_url_or_skip() -> str:
    url = os.getenv("OZ_REDIS_URL", "").strip()
    required = os.getenv("OZ_REQUIRE_REDIS_TESTS") == "1"
    if not url:
        if required:
            pytest.fail("OZ_REDIS_URL must be set when OZ_REQUIRE_REDIS_TESTS=1")
        pytest.skip("OZ_REDIS_URL is not set; skipping real Redis integration test")
    return url


def test_login_rate_limit_uses_real_redis(client, monkeypatch):
    url = _redis_url_or_skip()
    real_redis = redis.Redis.from_url(url)
    real_redis.ping()

    monkeypatch.setattr(settings, "redis_url", url)
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 3)
    # Keep the rate-limit window stable so the test cannot straddle a minute.
    monkeypatch.setattr(rate_limit.time, "time", lambda: 1_800_000_000)
    reset_rate_limiter_state()

    email = f"redis-limit-{uuid.uuid4().hex[:10]}@example.com"
    pattern = f"oz:rl:auth:*{email}*"
    for key in real_redis.keys(pattern):
        real_redis.delete(key)

    try:
        for _ in range(3):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "WrongPassword9"},
            )
            assert response.status_code == 401, response.text

        limited = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword9"},
        )
        assert limited.status_code == 429, limited.text
        assert limited.json()["error"]["code"] == "rate_limited"

        # Prove the limiter used Redis, not the in-process fallback.
        assert real_redis.keys(pattern), "rate limiter did not write the bucket to Redis"
    finally:
        for key in real_redis.keys(pattern):
            real_redis.delete(key)
        reset_rate_limiter_state()
