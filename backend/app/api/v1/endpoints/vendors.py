"""
Vendor Management API
Vendors are Party records with party_type='vendor' (or 'both').

GET    /vendors           — search/list
POST   /vendors           — create
GET    /vendors/{id}      — get by id
PATCH  /vendors/{id}      — update
DELETE /vendors/{id}      — deactivate
POST   /vendors/{id}/contacts — add contact
GET    /vendors/{id}/payables — outstanding payables summary
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import (
    CacheDep, CurrentUserDep, DBDep, PaginationDep, require_perm,
)
from app.schemas import PartyContactCreate, PartyContactOut, PartyCreate, PartyOut, PartyUpdate
from app.services import PartyService
from app.utils.responses import created, ok, paginated

from sqlalchemy import select,text
from sqlalchemy.orm import selectinload
from app.db.models import Party

router = APIRouter()


@router.get("", summary="Search / list vendors", dependencies=[require_perm("vendor.read")])
async def list_vendors(
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    cache: CacheDep,
    q: str | None = Query(None, description="Search name / GSTIN / phone / email / code"),
    city: str | None = Query(None),
    active_only: bool = Query(True),
) -> ORJSONResponse:
    cache_key = cache.cache_key(
        "vendors", str(current.company_id), q or "", city or "",
        str(pg.page), str(pg.page_size),
    )
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content=cached)

    svc = PartyService(db)
    result = await svc.search(
        company_id=current.company_id,
        party_type="vendor",
        query=q,
        city=city,
        active_only=active_only,
        page=pg.page,
        page_size=pg.page_size,
    )
    party_ids = [p.id for p in result.items]
    stats_by_vendor: dict[str, dict] = {}
    if party_ids:
        stmt = text("""
            SELECT
                vendor_id,
                COALESCE(SUM(total_amount) FILTER (WHERE status != 'cancelled'), 0) AS total_business,
                COALESCE(SUM(total_amount - paid_amount) FILTER (WHERE status NOT IN ('cancelled')), 0) AS payable,
                MAX(po_date) FILTER (WHERE status != 'cancelled') AS last_purchase
            FROM purchase_orders
            WHERE company_id = :cid AND vendor_id = ANY(:pids)
            GROUP BY vendor_id
        """)
        rows = (await db.execute(stmt, {"cid": str(current.company_id), "pids": [str(pid) for pid in party_ids]})).mappings().all()
        stats_by_vendor = {str(r["vendor_id"]): dict(r) for r in rows}

    items = []
    for p in result.items:
        item = PartyOut.model_validate(p).model_dump(mode="json")
        stats = stats_by_vendor.get(str(p.id), {})
        item["total_business"] = float(stats.get("total_business", 0))
        item["outstanding_amount"] = float(stats.get("payable", 0))
        item["last_purchase_date"] = stats.get("last_purchase").isoformat() if stats.get("last_purchase") else None
        items.append(item)
    resp = {
        "success": True, "message": "OK",
        "data": {"items": items, "total": result.total,
                 "page": result.page, "page_size": result.page_size, "pages": result.pages},
    }
    await cache.set(cache_key, resp, ttl=60)
    return ORJSONResponse(content=resp)


@router.post(
    "",
    summary="Create a vendor",
    status_code=201,
    dependencies=[require_perm("vendor.create")],  # type: ignore[list-item]
)
async def create_vendor(
    payload: PartyCreate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    if payload.party_type not in ("vendor", "both"):
        payload = payload.model_copy(update={"party_type": "vendor"})
    svc = PartyService(db)
    party = await svc.create(current.company_id, payload, current.user_id)
    await cache.delete_pattern(f"vendors:{current.company_id}:*")
    stmt = (select(Party).where(Party.id == party.id).options(selectinload(Party.contacts)))
    result = await db.execute(stmt)
    party_loaded = result.scalar_one()
    return created(
        data=PartyOut.model_validate(party_loaded).model_dump(mode="json"),
        message="Vendor created successfully.",
    )


@router.get("/{vendor_id}", summary="Get vendor by ID", dependencies=[require_perm("vendor.read")])
async def get_vendor(
    vendor_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.db.models import Party
    stmt = (
        select(Party)
        .where(Party.id == vendor_id, Party.company_id == current.company_id)
        .options(selectinload(Party.contacts))
    )
    result = await db.execute(stmt)
    party = result.scalar_one_or_none()
    if not party:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Vendor not found.")
    return ok(data=PartyOut.model_validate(party).model_dump(mode="json"))


@router.patch(
    "/{vendor_id}",
    summary="Update vendor",
    dependencies=[require_perm("vendor.update")],  # type: ignore[list-item]
)
async def update_vendor(
    vendor_id: UUID,
    payload: PartyUpdate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    svc = PartyService(db)
    party = await svc.update(vendor_id, payload, current.company_id, current.user_id)
    await cache.delete_pattern(f"vendors:{current.company_id}:*")
    stmt = (select(Party).where(Party.id == party.id).options(selectinload(Party.contacts)))
    result = await db.execute(stmt)
    party_loaded = result.scalar_one()
    return ok(data=PartyOut.model_validate(party_loaded).model_dump(mode="json"), message="Vendor updated.")


@router.delete(
    "/{vendor_id}",
    summary="Deactivate vendor",
    dependencies=[require_perm("vendor.delete")],  # type: ignore[list-item]
)
async def delete_vendor(
    vendor_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    from app.db.repositories import PartyRepository
    repo = PartyRepository(db)
    await repo.soft_delete(vendor_id)
    await cache.delete_pattern(f"vendors:{current.company_id}:*")
    return ok(message="Vendor deactivated.")


@router.post("/{vendor_id}/contacts", summary="Add contact person to vendor", dependencies=[require_perm("vendor.update")])
async def add_contact(
    vendor_id: UUID,
    payload: PartyContactCreate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.models import PartyContact
    contact = PartyContact(party_id=vendor_id, **payload.model_dump())
    db.add(contact)
    await db.flush()
    await db.refresh(contact)
    return created(
        data=PartyContactOut.model_validate(contact).model_dump(mode="json"),
        message="Contact added.",
    )


@router.get("/{vendor_id}/payables", summary="Vendor outstanding payables summary", dependencies=[require_perm("vendor.read")])
async def vendor_payables(
    vendor_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    return ok(data={
        "vendor_id": str(vendor_id),
        "total_billed": 0,
        "total_paid": 0,
        "balance_payable": 0,
        "bills": [],
    })
