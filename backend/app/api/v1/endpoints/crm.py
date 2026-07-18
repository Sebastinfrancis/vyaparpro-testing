"""CRM Leads API — GET/POST /crm/leads, GET/PATCH/DELETE /crm/leads/{id}"""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import CurrentUserDep, DBDep, PaginationDep
from app.schemas.crm import LeadCreate, LeadOut, LeadUpdate
from app.services.crm import CRMService
from app.utils.responses import created, ok

router = APIRouter()


@router.get("", summary="List leads")
async def list_leads(
    current: CurrentUserDep, db: DBDep, pg: PaginationDep,
    q: str | None = Query(None), stage: str | None = Query(None),
) -> ORJSONResponse:
    svc = CRMService(db)
    result = await svc.search(company_id=current.company_id, query=q, stage=stage, page=pg.page, page_size=pg.page_size)
    items = [LeadOut.model_validate(l).model_dump(mode="json") for l in result.items]
    return ORJSONResponse(content={
        "success": True, "message": "OK",
        "data": {"items": items, "total": result.total, "page": result.page,
                 "page_size": result.page_size, "pages": result.pages},
    })


@router.post("", summary="Create lead", status_code=201)
async def create_lead(payload: LeadCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = CRMService(db)
    lead = await svc.create(current.company_id, payload, current.user_id)
    return created(data=LeadOut.model_validate(lead).model_dump(mode="json"), message="Lead created.")


@router.get("/{lead_id}", summary="Get lead")
async def get_lead(lead_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = CRMService(db)
    lead = await svc.leads.get_or_raise(lead_id)
    return ok(data=LeadOut.model_validate(lead).model_dump(mode="json"))


@router.patch("/{lead_id}", summary="Update lead")
async def update_lead(lead_id: UUID, payload: LeadUpdate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = CRMService(db)
    lead = await svc.update(lead_id, payload, current.company_id, current.user_id)
    return ok(data=LeadOut.model_validate(lead).model_dump(mode="json"), message="Lead updated.")


@router.delete("/{lead_id}", summary="Deactivate lead")
async def delete_lead(lead_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = CRMService(db)
    await svc.leads.soft_delete(lead_id)
    return ok(message="Lead deactivated.")