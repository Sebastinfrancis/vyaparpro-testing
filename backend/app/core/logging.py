"""
VyaparPro — Logging Configuration
Structured JSON logging via loguru. Integrates with Sentry in production.
"""
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from typing import Any

import sentry_sdk
from loguru import logger
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings


class InterceptHandler(logging.Handler):
    """Route stdlib logging to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno  # type: ignore[assignment]

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _json_serializer(record: dict[str, Any]) -> str:
    import orjson

    payload = {
        "ts": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "module": record["module"],
        "func": record["function"],
        "line": record["line"],
        "msg": record["message"],
        **record["extra"],
    }
    if record["exception"]:
        payload["exc"] = str(record["exception"])
    return orjson.dumps(payload).decode() + "\n"


@lru_cache(maxsize=1)
def configure_logging() -> None:
    """Configure loguru and optionally Sentry. Call once at startup."""
    logger.remove()

    if settings.LOG_FORMAT == "json":
        logger.add(sys.stdout, level=settings.LOG_LEVEL)
    else:
        logger.add(
            sys.stdout,
            colorize=True,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
                "<level>{message}</level>"
            ),
            level=settings.LOG_LEVEL,
        )

    # File sink (production)
    if settings.APP_ENV == "production":
        logger.add(
            "logs/vyaparpro_{time:YYYY-MM-DD}.log",
            rotation="00:00",
            retention="30 days",
            compression="gz",
            serialize=True,
            level="INFO",
        )

    # Intercept stdlib loggers
    for name in ["uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine", "celery"]:
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False

    # Sentry
    if settings.SENTRY_DSN and settings.APP_ENV == "production":
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.APP_ENV,
            release=settings.APP_VERSION,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("Sentry initialized")

    logger.info(
        "Logging configured",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
        level=settings.LOG_LEVEL,
    )


def get_logger(name: str) -> "logger":  # type: ignore[valid-type]
    return logger.bind(name=name)
