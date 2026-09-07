from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Chowly application configuration.

    Values are never hardcoded here.

    Local development:
        Loaded from backend/.env

    Production / Render:
        Loaded from process environment variables.

    Every variable uses the CHOWLY_ prefix.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CHOWLY_",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Infrastructure
    # ------------------------------------------------------------------

    database_url: str
    redis_url: str

    # ------------------------------------------------------------------
    # Browser / networking
    # ------------------------------------------------------------------

    cors_origins: str

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------

    realtime_signing_secret: str
    session_signing_secret: str

    session_cookie_name: str
    session_ttl_minutes: int
    session_cookie_secure: bool

    invitation_ttl_hours: int

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    environment: str

    # ------------------------------------------------------------------
    # Demo / assessor mode
    # ------------------------------------------------------------------

    demo_mode: bool
    demo_tenant_ordinal: int

    # ------------------------------------------------------------------
    # Realtime
    # ------------------------------------------------------------------

    websocket_heartbeat_seconds: float
    websocket_heartbeat_grace_count: int
    event_history_limit: int

    # ------------------------------------------------------------------
    # Background jobs
    # ------------------------------------------------------------------

    job_state_ttl_seconds: int

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def is_development(self) -> bool:
        return self.environment.strip().lower() in {
            "development",
            "dev",
            "local",
            "test",
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if not self.database_url.strip():
            raise ValueError(
                "CHOWLY_DATABASE_URL must be configured."
            )

        if not self.redis_url.strip():
            raise ValueError(
                "CHOWLY_REDIS_URL must be configured."
            )

        if not self.cors_origin_list:
            raise ValueError(
                "CHOWLY_CORS_ORIGINS must contain at least one origin."
            )

        if self.session_ttl_minutes < 1:
            raise ValueError(
                "CHOWLY_SESSION_TTL_MINUTES must be positive."
            )

        if self.invitation_ttl_hours < 1:
            raise ValueError(
                "CHOWLY_INVITATION_TTL_HOURS must be positive."
            )

        if self.websocket_heartbeat_seconds <= 0:
            raise ValueError(
                "CHOWLY_WEBSOCKET_HEARTBEAT_SECONDS must be positive."
            )

        if self.websocket_heartbeat_grace_count < 1:
            raise ValueError(
                "CHOWLY_WEBSOCKET_HEARTBEAT_GRACE_COUNT must be positive."
            )

        if self.event_history_limit < 1:
            raise ValueError(
                "CHOWLY_EVENT_HISTORY_LIMIT must be positive."
            )

        if self.job_state_ttl_seconds < 1:
            raise ValueError(
                "CHOWLY_JOB_STATE_TTL_SECONDS must be positive."
            )

        if not 1 <= self.demo_tenant_ordinal <= 7:
            raise ValueError(
                "CHOWLY_DEMO_TENANT_ORDINAL must be between 1 and 7."
            )

        if (
            self.session_signing_secret
            == self.realtime_signing_secret
        ):
            raise ValueError(
                "Session and realtime signing secrets must be different."
            )

        if not self.is_development:
            secrets = (
                self.session_signing_secret,
                self.realtime_signing_secret,
            )

            if any(
                len(secret) < 32
                for secret in secrets
            ):
                raise ValueError(
                    "Production signing secrets must each be "
                    "at least 32 characters long."
                )

            if not self.session_cookie_secure:
                raise ValueError(
                    "Production staff session cookies must be secure."
                )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()