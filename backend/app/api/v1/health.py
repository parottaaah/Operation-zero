"""Health, readiness and lightweight metrics endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine

router = APIRouter(tags=["platform"])

VERSION = "0.1.0"
STARTED_AT = time.time()
REQUEST_COUNTER: dict[tuple[str, str, int], int] = {}
REQUEST_LATENCY: dict[str, float] = {}


def record_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    key = (method, path, status_code)
    REQUEST_COUNTER[key] = REQUEST_COUNTER.get(key, 0) + 1
    REQUEST_LATENCY[path] = REQUEST_LATENCY.get(path, 0.0) + duration_ms


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": settings.service_name, "version": VERSION}


@router.get("/readyz")
def readyz() -> Response:
    database = "ok"
    redis_status = "disabled"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    if settings.redis_url:
        redis_status = "error"
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            client.ping()
            redis_status = "ok"
        except Exception:
            redis_status = "error"
    ready = database == "ok" and redis_status != "error"
    body = {
        "status": "ready" if ready else "not_ready",
        "database": database,
        "redis": redis_status,
        "version": VERSION,
    }
    import json

    return Response(
        content=json.dumps(body),
        status_code=200 if ready else 503,
        media_type="application/json",
    )


@router.get("/metrics")
def metrics() -> Response:
    lines = [
        "# HELP oz_uptime_seconds Process uptime in seconds",
        "# TYPE oz_uptime_seconds gauge",
        f"oz_uptime_seconds {time.time() - STARTED_AT:.0f}",
        "# HELP oz_requests_total HTTP requests processed",
        "# TYPE oz_requests_total counter",
    ]
    for (method, path, status_code), count in sorted(REQUEST_COUNTER.items()):
        lines.append(f'oz_requests_total{{method="{method}",path="{path}",status="{status_code}"}} {count}')
    lines += [
        "# HELP oz_request_duration_ms_total Cumulative request duration per path",
        "# TYPE oz_request_duration_ms_total counter",
    ]
    for path, total in sorted(REQUEST_LATENCY.items()):
        lines.append(f'oz_request_duration_ms_total{{path="{path}"}} {total:.2f}')
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/api/v1/meta")
def meta() -> dict:
    return {
        "product": "OPERATION ZERO",
        "version": VERSION,
        "environment": settings.env,
        "ai_provider": settings.ai_provider,
        "ai_available": settings.ai_provider != "none",
        "github_configured": bool(settings.github_client_id and settings.github_client_secret),
        "github_webhooks_configured": bool(settings.github_webhook_secret),
        "max_log_query_range_days": settings.max_log_query_range_days,
        "max_log_batch_events": settings.max_log_batch_events,
        "max_log_payload_bytes": settings.max_log_payload_bytes,
        "allow_private_health_checks": settings.allow_private_health_checks,
    }


__all__ = ["router", "record_request", "VERSION"]
