"""
VyaparPro — FastAPI Dependencies
JWT auth, RBAC permission guards, pagination, Redis cache.
"""
from __future__ import annotations

from functools import wraps
from typing import Annotated, Any, Callable
from uuid import UUID

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    PermissionDeniedError, TokenInvalidError, AuthError
)
from app.core.security import decode_token
from app.db.database import get_db, set_rls_context
from app.db.repositories import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


# ── Current user ─────────────────────────────────────────────────────────────

class CurrentUser:
    """Parsed JWT claims injected into route handlers."""
    __slots__ = ("user_id", "company_id", "role_id", "branch_id", "scopes", "raw")

    def __init__(self, payload: dict[str, Any]) -> None:
        self.user_id = UUID(payload["sub"])
        self.company_id = UUID(payload["company_id"])
        self.role_id = UUID(payload["role_id"])
        self.branch_id = UUID(payload["branch_id"]) if payload.get("branch_id") else None
        self.scopes: list[str] = payload.get("scopes", [])
        self.raw = payload

    def has_permission(self, perm: str) -> bool:
        return perm in self.scopes

    def require_permission(self, perm: str) -> None:
        if not self.has_permission(perm):
            raise PermissionDeniedError(f"Missing permission: {perm}")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> CurrentUser:
    if not credentials:
        raise TokenInvalidError("Authorization header missing.")

    payload = decode_token(credentials.credentials, expected_type="access")
    current = CurrentUser(payload)

    # Set PostgreSQL RLS context
    await set_rls_context(db, company_id=current.company_id, user_id=current.user_id)

    # Attach to request state for middleware access
    request.state.current_user = current
    return current


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DBDep = Annotated[AsyncSession, Depends(get_db)]


# ── Permission guard factory ─────────────────────────────────────────────────

def require_perm(*permissions: str) -> Callable:
    """
    FastAPI dependency factory that enforces one or more permissions.
    Usage:
        @router.get("/", dependencies=[Depends(require_perm("invoice.read"))])
    """
    async def _guard(current: CurrentUserDep) -> CurrentUser:
        for perm in permissions:
            current.require_permission(perm)
        return current

    return Depends(_guard)


def require_any_perm(*permissions: str) -> Callable:
    """Allow if user has ANY of the listed permissions."""
    async def _guard(current: CurrentUserDep) -> CurrentUser:
        if not any(current.has_permission(p) for p in permissions):
            raise PermissionDeniedError(f"Requires any of: {', '.join(permissions)}")
        return current
    return Depends(_guard)


# ── Branch-level access scoping ────────────────────────────────────────────
# A user assigned to a specific branch (current.branch_id is set) should
# only be able to transact against that branch, no matter what other
# permissions their role grants — that's what "assigned to a branch" means
# in a real ERP. Users with no branch assignment (branch_id is None) are
# treated as company-wide staff (e.g. an owner/admin covering everything).
# The 'branch.access_all' permission is an explicit escape hatch for roles
# like a regional manager who legitimately needs to act across branches
# despite having a "home" branch on their profile.

def assert_branch_access(current: CurrentUser, branch_id: UUID | None) -> None:
    if current.branch_id is None:
        return  # company-wide user — no restriction
    if current.has_permission("branch.access_all"):
        return  # explicit override
    if branch_id is None:
        # A branch-scoped user must always specify a branch on transactions —
        # letting it default away would let it silently land in the wrong
        # place (or nowhere), which is worse than a clear rejection.
        raise PermissionDeniedError("This action requires selecting a branch.")
    if branch_id != current.branch_id:
        raise PermissionDeniedError("You can only do this for your own assigned branch.")


async def assert_warehouse_branch_access(db: AsyncSession, current: CurrentUser, warehouse_id: UUID) -> None:
    """Same check, but starting from a warehouse_id (transfers deal in warehouses, not branches directly)."""
    if current.branch_id is None or current.has_permission("branch.access_all"):
        return
    from app.db.repositories.inventory import WarehouseRepository
    wh = await WarehouseRepository(db).get_or_raise(warehouse_id)
    if wh.branch_id != current.branch_id:
        raise PermissionDeniedError("You can only do this for your own assigned branch.")


# ── Pagination ───────────────────────────────────────────────────────────────

class PaginationParams:
    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="Page number (1-based)"),
        page_size: int = Query(
            default=settings.DEFAULT_PAGE_SIZE,
            ge=1,
            le=settings.MAX_PAGE_SIZE,
            description="Items per page",
        ),
    ) -> None:
        self.page = page
        self.page_size = page_size


PaginationDep = Annotated[PaginationParams, Depends(PaginationParams)]


# ── Redis cache ──────────────────────────────────────────────────────────────

_redis_pool: Redis | None = None


async def get_redis() -> Redis:
    global _redis_pool
    if _redis_pool is None:
        from redis.asyncio import from_url
        _redis_pool = await from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool


RedisDep = Annotated[Redis, Depends(get_redis)]


class CacheService:
    """Simple Redis cache helper."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def get(self, key: str) -> Any | None:
        import orjson
        raw = await self.redis.get(key)
        return orjson.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: int = settings.REDIS_CACHE_TTL) -> None:
        import orjson
        await self.redis.setex(key, ttl, orjson.dumps(value))

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def delete_pattern(self, pattern: str) -> None:
        keys = await self.redis.keys(pattern)
        if keys:
            await self.redis.delete(*keys)

    def cache_key(self, *parts: str | UUID) -> str:
        return ":".join(str(p) for p in parts)


async def get_cache(redis: RedisDep) -> CacheService:
    return CacheService(redis)


CacheDep = Annotated[CacheService, Depends(get_cache)]


# ── Company scope guard ──────────────────────────────────────────────────────

async def verify_company_access(
    company_id: UUID,
    current: CurrentUserDep,
) -> UUID:
    """Ensure the requesting user belongs to the requested company."""
    if current.company_id != company_id:
        raise PermissionDeniedError("Access to this company is not allowed.")
    return company_id


CompanyScopeDep = Annotated[UUID, Depends(verify_company_access)]
