"""Permission listing endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import CurrentUserDep, DBDep
from app.schemas import PermissionOut
from app.services import RoleService
from app.utils.responses import ok

router = APIRouter()


@router.get("", summary="List all available permissions (optionally filtered by module)")
async def list_permissions(
    current: CurrentUserDep,
    db: DBDep,
    module: str | None = Query(None, description="Filter by module name"),
) -> ORJSONResponse:
    svc = RoleService(db)
    perms = await svc.list_permissions()
    if module:
        perms = [p for p in perms if p.module == module]
    return ok(data=[PermissionOut.model_validate(p).model_dump() for p in perms])
