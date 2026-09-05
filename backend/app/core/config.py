from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CHOWLY_")

    database_url: str = "sqlite:///./chowly.db"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"
    realtime_signing_secret: str = "local-development-secret-change-me-123456789"
    session_signing_secret: str = "local-session-secret-change-me-123456789012"
    session_cookie_name: str = "chowly_staff_session"
    session_ttl_minutes: int = 480
    session_cookie_secure: bool = False
    invitation_ttl_hours: int = 48
    environment: str = "development"
    websocket_heartbeat_seconds: float = 25.0
    websocket_heartbeat_grace_count: int = 2
    event_history_limit: int = 500
    job_state_ttl_seconds: int = 2_592_000

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment.strip().lower() in {"development", "dev", "local", "test"}

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.session_ttl_minutes < 1 or self.invitation_ttl_hours < 1:
            raise ValueError("Session and invitation lifetimes must be positive.")
        if not self.is_development:
            secrets = (self.session_signing_secret, self.realtime_signing_secret)
            if any(len(secret) < 32 or "change-me" in secret for secret in secrets):
                raise ValueError("Production signing secrets must be independently configured.")
            if not self.session_cookie_secure:
                raise ValueError("Production staff session cookies must be secure.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
