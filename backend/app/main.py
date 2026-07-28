"""
VyaparPro ERP — FastAPI Application Entry Point
Wires together: lifespan, middleware, routers, exception handlers, OpenAPI.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from pydantic import ValidationError as PydanticValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.exceptions import VyaparProError
from app.core.logging import configure_logging, get_logger
from app.db.database import check_db_connection, engine
from app.middleware.audit import AuditMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.timing import TimingMiddleware

from fastapi.staticfiles import StaticFiles
from pathlib import Path

# ── Route imports ────────────────────────────────────────────────────────────
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.users import router as users_router
from app.api.v1.endpoints.roles import router as roles_router
from app.api.v1.endpoints.permissions import router as permissions_router
from app.api.v1.endpoints.sessions import router as sessions_router
from app.api.v1.endpoints.companies import router as companies_router
from app.api.v1.endpoints.branches import router as branches_router
from app.api.v1.endpoints.customers import router as customers_router
from app.api.v1.endpoints.vendors import router as vendors_router
from app.api.v1.endpoints.products import router as products_router
from app.api.v1.endpoints.master import router as master_router
from app.api.v1.endpoints.billing import router as billing_router 
from app.api.v1.endpoints.crm import router as crm_router
from app.api.v1.endpoints.accounting import router as accounting_router
from app.api.v1.endpoints.reports import router as reports_router
from app.api.v1.endpoints.gst import router as gst_router

log = get_logger(__name__)

# ── Rate limiter (shared) ────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    log.info("VyaparPro starting", env=settings.APP_ENV, version=settings.APP_VERSION)

    # DB health check
    if not await check_db_connection():
        log.critical("Database unreachable — aborting startup")
        raise RuntimeError("Cannot connect to PostgreSQL")

    # Redis ping
    #try:
    #    from app.api.v1.dependencies import get_redis
     #   redis = await get_redis()
      #  await redis.ping()
       # log.info("Redis connected")
    #except Exception as exc:
        #log.warning("Redis ping failed — caching disabled", error=str(exc))

    log.info("Startup complete")
    yield

    # Teardown
    await engine.dispose()
    log.info("Database engine disposed — shutdown complete")


# ── App factory ───────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Production-grade ERP API for Indian SMBs",
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url="/redoc" if settings.APP_ENV != "production" else None,
        openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    origins = ["http://localhost:5500", "http://127.0.1:5500", "http://localhost:5173"]  # Allow local static file access during development

    # ── Middleware (order matters: outermost first) ────────────────────
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    static_dir = Path("app/static")
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    # ── Exception handlers ────────────────────────────────────────────
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(VyaparProError, _domain_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    # ── Routers ───────────────────────────────────────────────────────
    prefix = settings.API_V1_PREFIX
    app.include_router(auth_router,        prefix=f"{prefix}/auth",        tags=["Auth"])
    app.include_router(users_router,       prefix=f"{prefix}/users",       tags=["Users"])
    app.include_router(roles_router,       prefix=f"{prefix}/roles",       tags=["Roles"])
    app.include_router(permissions_router, prefix=f"{prefix}/permissions",  tags=["Permissions"])
    app.include_router(sessions_router,    prefix=f"{prefix}/sessions",    tags=["Sessions"])
    app.include_router(companies_router,   prefix=f"{prefix}/companies",   tags=["Companies"])
    app.include_router(branches_router,    prefix=f"{prefix}/companies/{{company_id}}/branches", tags=["Branches"])
    app.include_router(customers_router,   prefix=f"{prefix}/customers",   tags=["Customers"])
    app.include_router(vendors_router,     prefix=f"{prefix}/vendors",     tags=["Vendors"])
    app.include_router(products_router,    prefix=f"{prefix}/products",    tags=["Products"])
    app.include_router(master_router,      prefix=f"{prefix}/master",      tags=["Master Data"])
    app.include_router(billing_router,     prefix=f"{prefix}/billing",     tags=["Billing"])
    app.include_router(crm_router, prefix=f"{prefix}/crm/leads", tags=["CRM"])
    app.include_router(accounting_router, prefix=f"{prefix}/accounting", tags=["Accounting"])
    app.include_router(reports_router, prefix=f"{prefix}/reports", tags=["Reports"])
    app.include_router(gst_router, prefix=f"{prefix}/gst", tags=["GST"])
    

    # ── Health / readiness probes ─────────────────────────────────────
    @app.get("/health", include_in_schema=False)
    async def health() -> ORJSONResponse:
        db_ok = await check_db_connection()
        return ORJSONResponse(
            content={"status": "ok" if db_ok else "degraded", "db": db_ok},
            status_code=200 if db_ok else 503,
        )

    @app.get("/", include_in_schema=False)
    async def root() -> ORJSONResponse:
        return ORJSONResponse({"app": settings.APP_NAME, "version": settings.APP_VERSION})

    return app


# ── Exception handlers ────────────────────────────────────────────────────────

async def _domain_exception_handler(request: Request, exc: VyaparProError) -> ORJSONResponse:
    log.warning(
        "Domain exception",
        path=request.url.path,
        error_code=exc.error_code,
        message=exc.message,
    )
    return ORJSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": exc.error_code,
            "message": exc.message,
            "detail": exc.detail or None,
        },
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> ORJSONResponse:
    errors = [
        {"field": ".".join(str(l) for l in e["loc"][1:]), "message": e["msg"]}
        for e in exc.errors()
    ]
    return ORJSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error_code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "detail": errors,
        },
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> ORJSONResponse:
    log.exception("Unhandled exception", path=request.url.path, exc=str(exc))
    if settings.SENTRY_DSN:
        sentry_sdk.capture_exception(exc)
    return ORJSONResponse(
        status_code=500,
        content={
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred. Please try again.",
        },
    )


app = create_app()
