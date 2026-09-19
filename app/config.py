"""
Application configuration using Pydantic Settings.
All values are loaded from environment variables / .env file.
"""

from functools import lru_cache
from typing import Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_SECRET_KEY: str = "change-me-in-production-32-chars-min"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    PORT: int | None = None
    LOG_LEVEL: str = "INFO"
    FRONTEND_URL: str = "http://localhost:8000"
    ADMIN_EMAILS: str | list[str] = ["omichandra536@gmail.com"]

    # ── API Quota Limits ──────────────────────────────────────────────────────
    GEMINI_FREE_TIER_DAILY_LIMIT: int = 1500        # Requests per day (Gemini Flash free tier)
    GOOGLE_CALENDAR_DAILY_LIMIT: int = 1000000     # Google Calendar API queries per day

    # ── LLM ──────────────────────────────────────────────────────────────────
    GOOGLE_API_KEY: str = ""
    LLM_MODEL: str = "gemini-flash-latest"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096

    # ── Google OAuth ─────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/callback"
    GOOGLE_OAUTH_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid",
    ]

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_URI: str = ""
    MONGODB_USERNAME: str = ""
    MONGODB_PASSWORD: str = ""
    MONGODB_DB_NAME: str = "calender_agent"

    # ── LangSmith ────────────────────────────────────────────────────────────
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "calender-agent"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 30

    # ── Token Encryption ─────────────────────────────────────────────────────
    ENCRYPTION_KEY: str = ""

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @field_validator("ADMIN_EMAILS")
    @classmethod
    def parse_admin_emails(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [email.strip() for email in v.split(",") if email.strip()]
        return v or []

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return v.upper()

    @model_validator(mode="after")
    def sync_mongodb_settings(self) -> "Settings":
        """Ensure MONGODB_URL and MONGODB_URI are synchronized and propagate LangSmith settings."""
        import os
        # If MONGODB_URI is provided and MONGODB_URL is default/empty, use MONGODB_URI
        if self.MONGODB_URI and (not self.MONGODB_URL or self.MONGODB_URL == "mongodb://localhost:27017"):
            self.MONGODB_URL = self.MONGODB_URI
        elif self.MONGODB_URL and not self.MONGODB_URI:
            self.MONGODB_URI = self.MONGODB_URL

        if self.PORT is not None:
            self.APP_PORT = self.PORT

        if self.LANGCHAIN_TRACING_V2 and self.LANGCHAIN_API_KEY:
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = self.LANGCHAIN_API_KEY
            os.environ["LANGCHAIN_PROJECT"] = self.LANGCHAIN_PROJECT
            os.environ["LANGCHAIN_ENDPOINT"] = self.LANGCHAIN_ENDPOINT
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — call this everywhere."""
    return Settings()


# Global settings singleton
settings = get_settings()
