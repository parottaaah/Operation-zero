"""Application error types and consistent JSON error envelopes."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"


class PermissionDenied(AppError):
    status_code = 403
    code = "permission_denied"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


class SsrfBlocked(AppError):
    status_code = 400
    code = "ssrf_blocked"


__all__ = [
    "AppError",
    "ValidationFailed",
    "Unauthenticated",
    "PermissionDenied",
    "NotFound",
    "Conflict",
    "PayloadTooLarge",
    "RateLimited",
    "ServiceUnavailable",
    "SsrfBlocked",
]
