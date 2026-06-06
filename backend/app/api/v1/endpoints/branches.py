"""
Branch Management API (nested under /companies/{company_id}/branches)
Also exposed flat at /branches for convenience.
GET    /companies/{company_id}/branches         — list branches
POST   /companies/{company_id}/branches         — create branch
GET    /companies/{company_id}/branches/{id}    — get by id
PATCH  /companies/{company_id}/branches/{id}    — update
DELETE /companies/{company_id}/branches/{id}    — soft-delete
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import CurrentUserDep, DBDep, require_perm
from app.schemas import BranchCreate, BranchOut, BranchUpdate
from app.services import BranchService
from app.utils.responses import created, ok

router = APIRouter()


@router.get("", summary="List all branches for a company")
async def list_branches(
    company_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = BranchService(db)
    branches = await svc.list_by_company(company_id)
    return ok(data=[BranchOut.model_validate(b).model_dump() for b in branches])


@router.post(
    "",
    summary="Create a branch",
    status_code=201,
    dependencies=[require_perm("branch.create")],  # type: ignore[list-item]
)
async def create_branch(
    company_id: UUID,
    payload: BranchCreate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = BranchService(db)
    branch = await svc.create(company_id, payload, current.user_id)
    return created(data=BranchOut.model_validate(branch).model_dump(), message="Branch created.")


@router.get("/{branch_id}", summary="Get branch by ID")
async def get_branch(
    company_id: UUID,
    branch_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import BranchRepository
    repo = BranchRepository(db)
    branch = await repo.get_or_raise(branch_id)
    return ok(data=BranchOut.model_validate(branch).model_dump())


@router.patch(
    "/{branch_id}",
    summary="Update branch",
    dependencies=[require_perm("branch.update")],  # type: ignore[list-item]
)
async def update_branch(
    company_id: UUID,
    branch_id: UUID,
    payload: BranchUpdate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = BranchService(db)
    branch = await svc.update(branch_id, payload, company_id, current.user_id)
    return ok(data=BranchOut.model_validate(branch).model_dump(), message="Branch updated.")


@router.delete(
    "/{branch_id}",
    summary="Deactivate a branch",
    dependencies=[require_perm("branch.delete")],  # type: ignore[list-item]
)
async def delete_branch(
    company_id: UUID,
    branch_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import BranchRepository
    repo = BranchRepository(db)
    await repo.soft_delete(branch_id)
    return ok(message="Branch deactivated.")
