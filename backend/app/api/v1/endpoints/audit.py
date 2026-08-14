"""Audit Log API — GET (list, paginated) / POST (create) /audit-log"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import CurrentUserDep, DBDep, require_perm
from app.db.repositories import AuditLogRepository, UserRepository
from app.schemas import AuditLogCreate, AuditLogOut
from app.utils.responses import created, paginated

router = APIRouter()


@router.get("", summary="List audit log entries", dependencies=[require_perm("audit.read")])
async def list_audit_log(
    current: CurrentUserDep, db: DBDep,
    module: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ORJSONResponse:
    repo = AuditLogRepository(db)
    result = await repo.get_recent(company_id=current.company_id, module=module, page=page, page_size=page_size)
    items = [AuditLogOut.model_validate(l).model_dump(mode="json") for l in result.items]
    return paginated(items, result.total, result.page, result.page_size, result.pages)


@router.post("", summary="Create audit log entry", status_code=201)
async def create_audit_log(
    payload: AuditLogCreate, current: CurrentUserDep, db: DBDep, request: Request,
) -> ORJSONResponse:
    repo = AuditLogRepository(db)
    user = await UserRepository(db).get(current.user_id)
    entry = await repo.log(
        company_id=current.company_id,
        action=payload.action,
        module=payload.module,
        user_id=current.user_id,
        entity_type=payload.entity_type,
        entity_ref=payload.entity_ref,
        detail=payload.detail,
        actor_name=user.full_name if user else None,
        ip_address=request.client.host if request.client else None,
    )
    return created(data=AuditLogOut.model_validate(entry).model_dump(mode="json"))