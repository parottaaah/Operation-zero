"""FastAPI application factory and HTTP hardening middleware."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1 import api_router
from app.api.v1 import health as health_module
from app.core.config import settings
from app.core.errors import AppError
from app.core.observability import configure_logging

logger = logging.getLogger(__name__)

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings.validate_startup()
    if settings.auto_create_schema:
        if settings.is_production:  # pragma: no cover - guarded by validation
            raise RuntimeError("OZ_AUTO_CREATE_SCHEMA must not be used in production")
        from app.core.db import engine
        from app.models import Base

        Base.metadata.create_all(bind=engine)
        logger.warning("auto-created schema (development only)")

    import os

    os.makedirs(settings.reports_dir, exist_ok=True)
    task = None
    if settings.enable_background_workers:
        from app.workers.runner import run_forever

        task = asyncio.create_task(run_forever())
        logger.info("embedded background worker started")
    logger.info(
        "starting %s env=%s ai=%s github=%s",
        settings.service_name,
        settings.env,
        settings.ai_provider,
        bool(settings.github_client_id),
    )
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    app = FastAPI(
        title="OPERATION ZERO",
        version=VERSION,
        description=(
            "Unified engineering operations and incident intelligence platform. "
            "Monitoring, structured logs, alerts, incident workflow, deployment context "
            "and evidence-grounded AI assistance in one workspace."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Ingestion-Key",
            "Idempotency-Key",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID", "Content-Disposition"],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    @app.middleware("http")
    async def hardening(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > settings.max_request_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": "request body exceeds the configured limit",
                        "request_id": request_id,
                    }
                },
            )

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000

        route = request.scope.get("route")
        path_label = getattr(route, "path", request.url.path)
        health_module.record_request(request.method, path_label, response.status_code, duration_ms)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Cache-Control"] = "no-store"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
        if duration_ms > 1000:
            logger.warning(
                "slow request",
                extra={
                    "method": request.method,
                    "path": path_label,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        return response

    def _error_payload(request: Request, code: str, message: str, details=None) -> dict:
        return {
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": getattr(request.state, "request_id", ""),
            }
        }

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for error in exc.errors()[:20]:
            location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
            errors.append({"field": location, "message": error.get("msg", "invalid value")})
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                request, "validation_failed", "request validation failed", {"errors": errors}
            ),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("database integrity error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=409,
            content=_error_payload(request, "conflict", "the request conflicts with an existing record"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthenticated", 403: "permission_denied", 404: "not_found"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                request,
                "internal_error",
                "an unexpected error occurred; use the request id when contacting support",
            ),
        )

    app.include_router(health_module.router)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "product": "OPERATION ZERO",
            "version": VERSION,
            "docs": "/docs",
            "health": "/healthz",
            "api": "/api/v1",
        }

    return app


app = create_app()
