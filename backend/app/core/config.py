"""Application configuration.

All runtime configuration is read from environment variables prefixed with ``OZ_``.
Defaults are deliberately safe for local development and explicit in what must be
changed for production (see ``ProductionSafetyError`` below).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OZ_", env_file=(".env", "../.env"), extra="ignore", case_sensitive=False
    )

    # --- General ---------------------------------------------------------
    env: str = "development"
    debug: bool = False
    service_name: str = "operation-zero-api"
    api_base_url: str = "http://localhost:8000"
    public_web_url: str = "http://localhost:5173"

    # --- Data stores -----------------------------------------------------
    database_url: str = "sqlite:///./data/operation_zero.db"
    redis_url: str = ""
    auto_create_schema: bool = False

    # --- Auth ------------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 14
    password_min_length: int = 12
    encryption_key: str = ""

    # --- Web / HTTP ------------------------------------------------------
    # NoDecode keeps pydantic-settings from JSON-decoding these values, so the
    # documented CSV form (``a,b``) reaches the validator below instead of raising.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])
    trusted_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    # --- Limits ----------------------------------------------------------
    max_log_batch_events: int = 500
    max_log_payload_bytes: int = 262_144
    max_log_query_range_days: int = 7
    max_log_query_limit: int = 200
    ingest_rate_limit_per_minute: int = 600
    auth_rate_limit_per_minute: int = 20
    ai_rate_limit_per_minute: int = 10
    max_request_bytes: int = 1_048_576
    allow_private_health_checks: bool = False
    healthcheck_allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    max_healthcheck_redirects: int = 3

    # --- Workers ---------------------------------------------------------
    enable_background_workers: bool = False
    healthcheck_interval_seconds: int = 60
    alert_eval_interval_seconds: int = 60
    worker_batch_size: int = 50
    worker_max_backoff_seconds: int = 300
    worker_max_attempts: int = 3
    worker_retry_base_seconds: float = 0.5
    worker_retry_max_seconds: float = 4.0

    # --- Retention defaults ----------------------------------------------
    telemetry_default_retention_days: int = 30
    audit_default_retention_days: int = 365
    ai_default_retention_days: int = 90

    # --- GitHub ----------------------------------------------------------
    github_client_id: str = ""
    github_client_secret: str = ""
    github_webhook_secret: str = ""
    github_oauth_scopes: str = "read:user repo:status"
    github_api_url: str = "https://api.github.com"
    github_oauth_authorize_url: str = "https://github.com/login/oauth/authorize"
    github_oauth_token_url: str = "https://github.com/login/oauth/access_token"

    # --- AI --------------------------------------------------------------
    ai_provider: str = "none"  # none | openai_compatible
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout_seconds: int = 30
    ai_prompt_version: str = "ai-investigation/v1"

    # --- Email -----------------------------------------------------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    email_from: str = "alerts@operation-zero.local"

    # --- Storage ---------------------------------------------------------
    reports_dir: str = "./data/reports"

    @field_validator("cors_origins", "trusted_hosts", "healthcheck_allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept both the documented ``a,b`` form and a JSON array."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    # --- Derived helpers -------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod", "staging"}

    @property
    def fernet_key(self) -> bytes:
        """Return the symmetric key used to encrypt integration secrets at rest."""
        if self.encryption_key:
            return self.encryption_key.encode()
        # Deterministic development key. Production refuses to start without one.
        digest = hashlib.sha256(f"oz-dev-key:{self.jwt_secret}".encode()).digest()
        return base64.urlsafe_b64encode(digest)

    def production_problems(self) -> list[str]:
        problems: list[str] = []
        if not self.is_production:
            return problems
        if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("OZ_JWT_SECRET must be a unique secret of at least 32 characters")
        if not self.encryption_key:
            problems.append("OZ_ENCRYPTION_KEY must be set (Fernet key) in production")
        if "*" in self.cors_origins:
            problems.append("OZ_CORS_ORIGINS must not allow '*' in production")
        if self.debug:
            problems.append("OZ_DEBUG must be false in production")
        if not self.database_url.startswith("postgresql"):
            problems.append("OZ_DATABASE_URL must use PostgreSQL in production")
        return problems

    def validate_startup(self) -> None:
        problems = self.production_problems()
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))
        if self.jwt_secret == DEV_JWT_SECRET:
            logger.warning(
                "OZ_JWT_SECRET is the development default. Set a unique secret before any "
                "shared or public deployment."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

__all__ = ["Settings", "get_settings", "settings", "secrets"]
