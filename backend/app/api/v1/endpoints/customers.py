"""
Customer Management API
Customers are Party records with party_type='customer' (or 'both').

GET    /customers           — search with q, city, category, page filters
POST   /customers           — create
GET    /customers/{id}      — get by id (with contacts)
PATCH  /customers/{id}      — update
DELETE /customers/{id}      — deactivate
GET    /customers/{id}/statement — mini ledger summary (placeholder)
POST   /customers/{id}/contacts  — add contact person
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

from sqlalchemy import select, bindparam, text
from sqlalchemy.orm import selectinload
from app.db.models import Party

router = APIRouter()


@router.get("", summary="Search / list customers with filters", dependencies=[require_perm("customer.read")])
async def list_customers(
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    cache: CacheDep,
    q: str | None = Query(None, description="Search name / GSTIN / phone / email / code"),
    city: str | None = Query(None),
    category: str | None = Query(None, description="Party category e.g. retailer, individual"),
    active_only: bool = Query(True),
) -> ORJSONResponse:
    cache_key = cache.cache_key(
        "customers", str(current.company_id),
        q or "", city or "", category or "",
        str(pg.page), str(pg.page_size),
    )
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content=cached)

    svc = PartyService(db)
    result = await svc.search(
        company_id=current.company_id,
        party_type="customer",
        query=q,
        city=city,
        active_only=active_only,
        page=pg.page,
        page_size=pg.page_size,
    )
    party_ids = [p.id for p in result.items]
    stats_by_party: dict[str, dict] = {}
    if party_ids:
        stmt = text("""
            SELECT
                party_id,
                COALESCE(SUM(
                    CASE
                        WHEN invoice_type = 'credit_note' THEN -total_amount
                        ELSE total_amount
                    END
                ) FILTER (WHERE status NOT IN ('cancelled','void','draft')), 0) AS total_business,
                COALESCE(SUM(
                    CASE
                        WHEN invoice_type = 'credit_note' THEN -(total_amount - paid_amount)
                        ELSE (total_amount - paid_amount)
                    END
                ) FILTER (WHERE status NOT IN ('paid','cancelled','void','draft')), 0) AS outstanding,
                MAX(invoice_date) FILTER (WHERE status NOT IN ('cancelled','void','draft')) AS last_purchase
            FROM invoices
            WHERE company_id = :cid AND party_id IN :pids
            GROUP BY party_id
        """).bindparams(bindparam("pids", expanding=True))
        rows = (await db.execute(stmt, {"cid": str(current.company_id), "pids": [str(pid) for pid in party_ids]})).mappings().all()
        stats_by_party = {str(r["party_id"]): dict(r) for r in rows}

    items = []
    for p in result.items:
        item = PartyOut.model_validate(p).model_dump(mode="json")
        stats = stats_by_party.get(str(p.id), {})
        item["total_business"] = float(stats.get("total_business", 0))
        item["outstanding_amount"] = float(stats.get("outstanding", 0))
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
    summary="Create a customer",
    status_code=201,
    dependencies=[require_perm("customer.create")],  # type: ignore[list-item]
)
async def create_customer(
    payload: PartyCreate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    # Force party_type = customer if not 'both'
    if payload.party_type not in ("customer", "both"):
        payload = payload.model_copy(update={"party_type": "customer"})
    svc = PartyService(db)
    party = await svc.create(current.company_id, payload, current.user_id)
    await cache.delete_pattern(f"customers:{current.company_id}:*")
    stmt = (select(Party).where(Party.id == party.id).options(selectinload(Party.contacts)))
    result = await db.execute(stmt)
    party_loaded = result.scalar_one_or_none()
    return created(
        data=PartyOut.model_validate(party_loaded).model_dump(mode="json"),
        message="Customer created successfully.",
    )


@router.get("/{customer_id}", summary="Get customer by ID", dependencies=[require_perm("customer.read")])
async def get_customer(
    customer_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import PartyRepository
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.db.models import Party
    stmt = (
        select(Party)
        .where(Party.id == customer_id, Party.company_id == current.company_id)
        .options(selectinload(Party.contacts))
    )
    result = await db.execute(stmt)
    party = result.scalar_one_or_none()
    if not party:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Customer not found.")
    return ok(data=PartyOut.model_validate(party).model_dump(mode="json"))


@router.patch(
    "/{customer_id}",
    summary="Update customer",
    dependencies=[require_perm("customer.update")],  # type: ignore[list-item]
)
async def update_customer(
    customer_id: UUID,
    payload: PartyUpdate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    svc = PartyService(db)
    party = await svc.update(customer_id, payload, current.company_id, current.user_id)
    await cache.delete_pattern(f"customers:{current.company_id}:*")
    stmt = (select(Party).where(Party.id == party.id).options(selectinload(Party.contacts)))
    result = await db.execute(stmt)
    party_loaded = result.scalar_one()
    return ok(data=PartyOut.model_validate(party_loaded).model_dump(mode="json"), message="Customer updated.")


@router.delete(
    "/{customer_id}",
    summary="Deactivate customer",
    dependencies=[require_perm("customer.delete")],  # type: ignore[list-item]
)
async def delete_customer(
    customer_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    from app.db.repositories import PartyRepository
    repo = PartyRepository(db)
    await repo.soft_delete_scoped(customer_id, company_id=current.company_id)
    await cache.delete_pattern(f"customers:{current.company_id}:*")
    return ok(message="Customer deactivated.")


@router.post("/{customer_id}/contacts", summary="Add a contact person to customer", dependencies=[require_perm("customer.update")])
async def add_contact(
    customer_id: UUID,
    payload: PartyContactCreate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.models import PartyContact
    contact = PartyContact(party_id=customer_id, **payload.model_dump())
    db.add(contact)
    await db.flush()
    await db.refresh(contact)
    return created(
        data=PartyContactOut.model_validate(contact).model_dump(mode="json"),
        message="Contact added.",
    )


@router.get("/{customer_id}/statement", summary="Customer account statement summary", dependencies=[require_perm("customer.read")])
async def customer_statement(
    customer_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    # Placeholder — wire to invoice/payment tables in billing module
    return ok(data={
        "customer_id": str(customer_id),
        "total_invoiced": 0,
        "total_received": 0,
        "balance_due": 0,
        "invoices": [],
    })
