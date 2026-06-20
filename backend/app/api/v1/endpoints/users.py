"""
User Management endpoints
GET /users — search/list with filters & pagination
POST /users — create user
GET /users/{id} — get by id
PATCH /users/{id} — update
DELETE /users/{id} — soft-delete
POST /users/{id}/activate|deactivate
POST /users/{id}/reset-password — admin force reset
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import (
    CurrentUserDep, DBDep, PaginationDep, require_perm,
)
from app.schemas import UserCreate, UserOut, UserUpdate
from app.services import UserService
from app.utils.responses import created, ok, paginated
from app.db.models import User, Role

from sqlalchemy import select
from sqlalchemy.orm import selectinload

router = APIRouter()


@router.get(
    "",
    summary="List / search users",
    dependencies=[require_perm("user.read")],  # type: ignore[list-item]
)
async def list_users(
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    q: str | None = Query(None, description="Search name / email / phone"),
    role_id: UUID | None = Query(None),
    branch_id: UUID | None = Query(None),
    active_only: bool = Query(True),
) -> ORJSONResponse:
    svc = UserService(db)
    result = await svc.search(
        company_id=current.company_id,
        query=q,
        role_id=role_id,
        branch_id=branch_id,
        active_only=active_only,
        page=pg.page,
        page_size=pg.page_size,
    )
    items = [UserOut.model_validate(u).model_dump(mode="json") for u in result.items]
    return paginated(items, result.total, result.page, result.page_size, result.pages)


@router.post(
    "",
    summary="Create a new user",
    status_code=201,
    dependencies=[require_perm("user.create")],  # type: ignore[list-item]
)
async def create_user(
    payload: UserCreate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = UserService(db)
    user = await svc.create(
        company_id=current.company_id,
        payload=payload,
        created_by=current.user_id,
    )
    stmt = (select(User).where(User.id == user.id).options(selectinload(User.role).selectinload(Role.permissions)))
    result = await db.execute(stmt)
    user_loaded = result.scalar_one_or_none()
    return created(
        data=UserOut.model_validate(user_loaded).model_dump(mode="json"),
        message="User created successfully.",
    )


@router.get(
    "/{user_id}",
    summary="Get user by ID",
    dependencies=[require_perm("user.read")],  # type: ignore[list-item]
)
async def get_user(
    user_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = UserService(db)
    user = await svc.get_with_role(user_id)
    return ok(data=UserOut.model_validate(user).model_dump(mode="json"))


@router.patch(
    "/{user_id}",
    summary="Update user",
    dependencies=[require_perm("user.update")],  # type: ignore[list-item]
)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = UserService(db)
    user = await svc.update(
        user_id=user_id,
        payload=payload,
        company_id=current.company_id,
        actor_id=current.user_id,
    )
    stmt = (select(User).where(User.id == user.id).options(selectinload(User.role).selectinload(Role.permissions)))
    result = await db.execute(stmt)
    user_loaded = result.scalar_one()
    return ok(data=UserOut.model_validate(user_loaded).model_dump(mode="json"), message="User updated.")


@router.delete(
    "/{user_id}",
    summary="Soft-delete (deactivate) a user",
    dependencies=[require_perm("user.delete")],  # type: ignore[list-item]
)
async def delete_user(
    user_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import UserRepository
    repo = UserRepository(db)
    await repo.soft_delete(user_id)
    return ok(message="User deactivated.")


@router.post("/{user_id}/activate", summary="Re-activate a deactivated user")
async def activate_user(
    user_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import UserRepository
    repo = UserRepository(db)
    user = await repo.get_or_raise(user_id)
    await repo.update(user, {"is_active": True})
    return ok(message="User activated.")


@router.post(
    "/{user_id}/force-reset-password",
    summary="Admin: force password reset for a user",
    dependencies=[require_perm("user.update")],  # type: ignore[list-item]
)
async def force_reset_password(
    user_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import UserRepository, UserSessionRepository
    from app.core.security import create_reset_token
    repo = UserRepository(db)
    user = await repo.get_or_raise(user_id)
    token = create_reset_token(user.id, user.email)
    await UserSessionRepository(db).revoke_all_for_user(user_id)
    return ok(
        data={"reset_token": token, "note": "Send this token to the user via a secure channel."},
        message="All sessions revoked. Reset token generated.",
    )
