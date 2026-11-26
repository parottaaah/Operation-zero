"""Rate limiting.

Uses Redis when configured and reachable, with a bounded in-process fallback so a
single-node development deployment still behaves predictably. Fail-open on Redis
errors is intentional: losing the rate limiter must not take down monitoring, but
the failure is logged so operators can see it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from app.core.config import settings
from app.core.errors import RateLimited

logger = logging.getLogger(__name__)

_redis_client = None
_redis_checked = False
_redis_lock = threading.Lock()
_memory_lock = threading.Lock()
_memory_hits: dict[str, deque[float]] = defaultdict(deque)


def _get_redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    with _redis_lock:
        if _redis_checked:
            return _redis_client
        _redis_checked = True
        if not settings.redis_url:
            return None
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            client.ping()
            _redis_client = client
            logger.info("rate limiter using redis")
        except Exception as exc:  # pragma: no cover - depends on environment
            logger.warning("redis unavailable (%s); using in-process rate limiter", exc)
            _redis_client = None
    return _redis_client


def reset_rate_limiter_state() -> None:
    """Test helper: forget cached Redis client and in-memory buckets."""
    global _redis_client, _redis_checked
    with _redis_lock:
        _redis_client = None
        _redis_checked = False
    with _memory_lock:
        _memory_hits.clear()


def check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    if limit <= 0:
        return
    client = _get_redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            bucket = f"oz:rl:{key}:{int(time.time()) // window_seconds}"
            pipe.incr(bucket)
            pipe.expire(bucket, window_seconds + 2)
            count, _ = pipe.execute()
            if int(count) > limit:
                raise RateLimited(
                    "too many requests; please retry later",
                    details={"limit": limit, "window_seconds": window_seconds},
                )
            return
        except RateLimited:
            raise
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("redis rate limit failed (%s); falling back to memory", exc)

    now = time.monotonic()
    cutoff = now - window_seconds
    with _memory_lock:
        bucket = _memory_hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise RateLimited(
                "too many requests; please retry later",
                details={"limit": limit, "window_seconds": window_seconds},
            )
        bucket.append(now)


__all__ = ["check_rate_limit", "reset_rate_limiter_state"]
