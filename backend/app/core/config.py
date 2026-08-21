"""
VyaparPro — Application Settings
Loaded from environment variables / .env file via pydantic-settings.
"""
from __future__ import annotations

import secrets
from typing import Any, Literal

from pydantic import AnyHttpUrl, EmailStr, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────
    APP_NAME: str = "VyaparPro ERP"
    APP_VERSION: str = "2.0.0"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    SECRET_KEY: str = secrets.token_urlsafe(64)
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_HOSTS: list[str] = ["*"]
    ALLOWED_ORIGINS: list[AnyHttpUrl | str] = [
        "http://localhost:3000", "http://localhost:8080",
        "tauri://localhost",        # macOS / Linux Tauri webview
        "http://tauri.localhost",   # Windows Tauri webview (WebView2)
        "https://tauri.localhost",
    ]

    #------LICENSING--------------------------
    LICENSE_SERVER_URL: str = "https://license.vyaparpro.in/api/v1"
    LICENSE_PUBLIC_KEY: str = "91fc41abe83f60e044cf820d68bf41bd4e55f292bf3cb881d3e1c9242673e75e"
    LICENSE_GRACE_DAYS: int = 10
    LICENSE_CHECK_INTERVAL_HOURS: int = 24

    # ── JWT ──────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = secrets.token_urlsafe(64)
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_RESET_TOKEN_EXPIRE_MINUTES: int = 15

    # ── Database ─────────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "Bhuvanesh1310"
    POSTGRES_DB: str = "vyaparpro_db"
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 10
    POSTGRES_POOL_TIMEOUT: int = 30
    POSTGRES_ECHO: bool = False
    DB_ENGINE: Literal["postgresql", "sqlite"] = "postgresql"
    SQLITE_PATH: str = "vyaparpro.db"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        if self.DB_ENGINE == "sqlite":
            return f"sqlite+aiosqlite:///{self.SQLITE_PATH}"
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        if self.DB_ENGINE == "sqlite":
            return f"sqlite:///{self.SQLITE_PATH}"
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_CACHE_TTL: int = 300  # 5 minutes default
    REDIS_SESSION_TTL: int = 86400  # 24 hours

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ── Celery ───────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Email ────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp-relay.brevo.com"
    SMTP_PORT: int = 587
    SMTP_TLS: bool = True
    SMTP_USER: str = "b61d47001@smtp-brevo.com"
    SMTP_PASSWORD: str = "xsmtpsib-ed7960f2f0357749bbee48d8ff6b5294115783ca51855992ddbacd1ed712525d-6vBUlCvBVngmAL0V"
    EMAILS_FROM_EMAIL: EmailStr = "bhuvanesh1326@gmail.com"
    EMAILS_FROM_NAME: str = "VyaparPro ERP"

    # ── Storage (AWS S3) ─────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    AWS_S3_BUCKET: str = "vyaparpro-storage"
    AWS_S3_PREFIX: str = "uploads"

    # ── Security ─────────────────────────────────────────────────────
    BCRYPT_ROUNDS: int = 12
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 30
    PASSWORD_MIN_LENGTH: int = 8
    TOTP_ISSUER: str = "VyaparPro"

    # ── Rate Limiting ─────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10

    # ── Pagination ───────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 200

    # ── Sentry ───────────────────────────────────────────────────────
    SENTRY_DSN: str = ""

    # ── Logging ──────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json | text


settings = Settings()
