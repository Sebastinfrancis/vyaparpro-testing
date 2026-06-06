"""AuditMiddleware — structured access log for every HTTP request."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

log = get_logger(__name__)

_SKIP_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        response = await call_next(request)

        user_id = None
        if hasattr(request.state, "current_user"):
            user_id = str(request.state.current_user.user_id)

        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            user_id=user_id,
            request_id=getattr(request.state, "request_id", None),
            ip=request.client.host if request.client else None,
        )
        return response
