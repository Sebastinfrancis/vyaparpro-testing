"""Role Management endpoints — CRUD + permission assignment."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import CurrentUserDep, DBDep, require_perm
from app.schemas import RoleCreate, RoleOut, RoleUpdate
from app.services import RoleService
from app.utils.responses import created, ok

router = APIRouter()


@router.get(
    "", summary="List all roles in company",
    dependencies=[require_perm("role.read")],  # type: ignore[list-item]
)
async def list_roles(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = RoleService(db)
    roles = await svc.list_by_company(current.company_id)
    return ok(data=[RoleOut.model_validate(r).model_dump(mode="json") for r in roles])


@router.post(
    "",
    summary="Create a role",
    status_code=201,
    dependencies=[require_perm("role.create")],  # type: ignore[list-item]
)
async def create_role(
    payload: RoleCreate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = RoleService(db)
    role = await svc.create(current.company_id, payload, current.user_id)
    return created(data=RoleOut.model_validate(role).model_dump(mode="json"), message="Role created.")


@router.get(
    "/{role_id}", summary="Get role by ID with permissions",
    dependencies=[require_perm("role.read")],  # type: ignore[list-item]
)
async def get_role(role_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories import RoleRepository
    repo = RoleRepository(db)
    role = await repo.get_with_permissions(role_id)
    if not role:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Role not found.")
    return ok(data=RoleOut.model_validate(role).model_dump(mode="json"))


@router.patch(
    "/{role_id}",
    summary="Update role name/level/permissions",
    dependencies=[require_perm("role.update")],  # type: ignore[list-item]
)
async def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = RoleService(db)
    role = await svc.update(role_id, payload, current.company_id, current.user_id)
    return ok(data=RoleOut.model_validate(role).model_dump(mode="json"), message="Role updated.")


@router.delete(
    "/{role_id}",
    summary="Delete a non-system role",
    dependencies=[require_perm("role.delete")],  # type: ignore[list-item]
)
async def delete_role(role_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories import RoleRepository
    from app.core.exceptions import PermissionDeniedError
    repo = RoleRepository(db)
    role = await repo.get_or_raise(role_id)
    if role.is_system_role:
        raise PermissionDeniedError("System roles cannot be deleted.")
    await repo.delete(role)
    return ok(message="Role deleted.")
