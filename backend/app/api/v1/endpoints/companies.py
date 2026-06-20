"""
Company Management API
GET    /companies              — list/search (superadmin)
POST   /companies              — create company
GET    /companies/{id}         — get by id
PATCH  /companies/{id}         — update settings / details
DELETE /companies/{id}         — soft-delete
POST   /companies/{id}/logo    — upload logo
GET    /companies/{id}/summary — stats / KPI summary
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, UploadFile, File
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import (
    CacheDep, CurrentUserDep, DBDep, PaginationDep, require_perm,
)
from app.schemas import CompanyCreate, CompanyOut, CompanyUpdate
from app.services import CompanyService
from app.utils.responses import created, ok, paginated
from fastapi.encoders import jsonable_encoder

router = APIRouter()

_TTL = 120  # 2-minute cache for company reads


@router.get("", summary="Search / list companies")
async def list_companies(
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    cache: CacheDep,
    q: str | None = Query(None, description="Search by name or GSTIN"),
) -> ORJSONResponse:
    cache_key = cache.cache_key("companies", str(current.company_id), q or "", str(pg.page), str(pg.page_size))
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content=cached)

    svc = CompanyService(db)
    result = await svc.list(query=q, page=pg.page, page_size=pg.page_size)
    items = [CompanyOut.model_validate(c).model_dump() for c in result.items]
    resp = {
        "success": True, "message": "OK",
        "data": {"items": items, "total": result.total,
                 "page": result.page, "page_size": result.page_size, "pages": result.pages},
    }
    safe_resp = jsonable_encoder(resp)
    await cache.set(cache_key, safe_resp, ttl=_TTL)
    return ORJSONResponse(content=safe_resp)


@router.post(
    "",
    summary="Create a new company",
    status_code=201,
    dependencies=[require_perm("company.create")],  # type: ignore[list-item]
)
async def create_company(
    payload: CompanyCreate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    svc = CompanyService(db)
    company = await svc.create(payload, created_by=current.user_id)
    await cache.delete_pattern("companies:*")
    return created(
        data=CompanyOut.model_validate(company).model_dump(mode="json"),
        message="Company created successfully.",
    )


@router.get("/{company_id}", summary="Get company by ID")
async def get_company(
    company_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    cache_key = cache.cache_key("company", str(company_id))
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content={"success": True, "data": cached})

    from app.db.repositories import CompanyRepository
    repo = CompanyRepository(db)
    company = await repo.get_or_raise(company_id)
    data = CompanyOut.model_validate(company).model_dump()
    safe_data = jsonable_encoder(data)
    await cache.set(cache_key, safe_data, ttl=_TTL)
    return ok(data=safe_data)


@router.patch(
    "/{company_id}",
    summary="Update company details",
    dependencies=[require_perm("company.update")],  # type: ignore[list-item]
)
async def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    svc = CompanyService(db)
    company = await svc.update(company_id, payload, user_id=current.user_id)
    safe_data = jsonable_encoder(CompanyOut.model_validate(company).model_dump())
    await cache.delete(cache.cache_key("company", str(company_id)))
    await cache.delete_pattern("companies:*")
    return ok(data=safe_data, message="Company updated.")


@router.delete(
    "/{company_id}",
    summary="Deactivate a company",
    dependencies=[require_perm("company.delete")],  # type: ignore[list-item]
)
async def delete_company(
    company_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    from app.db.repositories import CompanyRepository
    repo = CompanyRepository(db)
    await repo.soft_delete(company_id)
    await cache.delete(cache.cache_key("company", str(company_id)))
    await cache.delete_pattern("companies:*")
    return ok(message="Company deactivated.")


@router.post("/{company_id}/logo", summary="Upload company logo (multipart)")
async def upload_logo(
    company_id: UUID,
    file: UploadFile,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    # Validate file type
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        from app.core.exceptions import ValidationError
        raise ValidationError("Only JPEG, PNG, or WebP images are accepted.")
    # In production: upload to S3, store URL in company.logo_url
    # For now, return a placeholder
    logo_url = f"/static/logos/{company_id}.png"
    from app.db.repositories import CompanyRepository
    repo = CompanyRepository(db)
    company = await repo.get_or_raise(company_id)
    await repo.update(company, {"logo_url": logo_url})
    return ok(data={"logo_url": logo_url}, message="Logo uploaded.")


@router.get("/{company_id}/summary", summary="Company dashboard KPI summary")
async def company_summary(
    company_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    cache_key = cache.cache_key("company_summary", str(company_id))
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content={"success": True, "data": cached})

    from sqlalchemy import func, select, text
    from app.db.models import User, Branch, Party, Product
    async def count(model, **filters):
        stmt = select(func.count()).where(
            *[getattr(model, k) == v for k, v in filters.items()]
        )
        return (await db.execute(stmt)).scalar_one()

    summary = {
        "branches": await count(Branch, company_id=company_id, is_active=True),
        "users": await count(User, company_id=company_id, is_active=True),
        "customers": 0,  # extend when invoice tables exist
        "vendors": 0,
        "products": await count(Product, company_id=company_id, is_active=True),
    }
    await cache.set(cache_key, summary, ttl=60)
    return ok(data=summary)
