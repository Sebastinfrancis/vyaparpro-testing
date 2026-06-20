"""
Master Data API — Categories · Brands · Units of Measure · GST Rates · HSN Codes

GET/POST/PATCH/DELETE /categories
GET/POST/PATCH/DELETE /brands
GET/POST /uoms
GET      /gst-rates
GET      /hsn-codes?q=...
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import (
    CacheDep, CurrentUserDep, DBDep, require_perm,
)
from app.schemas import (
    CategoryCreate, CategoryOut, CategoryUpdate,
    GSTRateOut, HSNCodeOut, UOMCreate, UOMOut,
)
from app.services import CategoryService, MasterDataService
from app.utils.responses import created, ok
from fastapi.encoders import jsonable_encoder

router = APIRouter()


# ════════════════════════════════════════════════════════════════════
# CATEGORIES
# ════════════════════════════════════════════════════════════════════

@router.get("/categories", summary="List all product categories (tree)")
async def list_categories(
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    cache_key = cache.cache_key("categories", str(current.company_id))
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content={"success": True, "data": cached})
    svc = CategoryService(db)
    cats = await svc.tree(current.company_id)
    data = [CategoryOut.model_validate(c).model_dump() for c in cats]
    safe_data = jsonable_encoder(data)
    await cache.set(cache_key, safe_data, ttl=300)
    return ok(data=safe_data)


@router.post(
    "/categories",
    summary="Create product category",
    status_code=201,
    dependencies=[require_perm("product.create")],  # type: ignore[list-item]
)
async def create_category(
    payload: CategoryCreate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    svc = CategoryService(db)
    cat = await svc.create(current.company_id, payload)
    await cache.delete(cache.cache_key("categories", str(current.company_id)))
    return created(data=CategoryOut.model_validate(cat).model_dump(mode='json'), message="Category created.")


@router.get("/categories/{cat_id}", summary="Get category by ID")
async def get_category(cat_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories import ProductCategoryRepository
    repo = ProductCategoryRepository(db)
    cat = await repo.get_or_raise(cat_id)
    return ok(data=CategoryOut.model_validate(cat).model_dump(mode='json'))

@router.patch(
    "/categories/{cat_id}",
    summary="Update category",
    dependencies=[require_perm("product.update")],  # type: ignore[list-item]
)
async def update_category(
    cat_id: UUID,
    payload: CategoryUpdate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    svc = CategoryService(db)
    cat = await svc.update(cat_id, payload, current.company_id)
    await cache.delete(cache.cache_key("categories", str(current.company_id)))
    return ok(data=CategoryOut.model_validate(cat).model_dump(mode='json'), message="Category updated.")


@router.delete(
    "/categories/{cat_id}",
    summary="Deactivate category",
    dependencies=[require_perm("product.delete")],  # type: ignore[list-item]
)
async def delete_category(
    cat_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    from app.db.repositories import ProductCategoryRepository
    repo = ProductCategoryRepository(db)
    await repo.soft_delete(cat_id)
    await cache.delete(cache.cache_key("categories", str(current.company_id)))
    return ok(message="Category deactivated.")


# ════════════════════════════════════════════════════════════════════
# BRANDS
# ════════════════════════════════════════════════════════════════════

@router.get("/brands", summary="List all brands for this company")
async def list_brands(
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
    q: str | None = Query(None),
) -> ORJSONResponse:
    from sqlalchemy import select, distinct, or_
    from app.db.models import Product

    cache_key = cache.cache_key("brands", str(current.company_id), q or "")
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content={"success": True, "data": cached})

    stmt = (
        select(distinct(Product.brand))
        .where(Product.company_id == current.company_id, Product.brand.isnot(None), Product.is_active == True)
        .order_by(Product.brand)
    )
    if q:
        stmt = stmt.where(Product.brand.ilike(f"%{q}%"))
    result = await db.execute(stmt)
    brands = [r for r in result.scalars().all() if r]
    await cache.set(cache_key, brands, ttl=300)
    return ok(data=brands)


@router.get("/brands/{brand_name}/products", summary="List products under a brand")
async def brand_products(
    brand_name: str,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.db.models import Product
    stmt = (
        select(Product)
        .where(
            Product.company_id == current.company_id,
            Product.brand == brand_name,
            Product.is_active == True,
        )
        .options(selectinload(Product.category), selectinload(Product.uom))
        .order_by(Product.product_name)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()
    from app.schemas import ProductOut
    return ok(data=[ProductOut.model_validate(p).model_dump(mode='json') for p in products])


# ════════════════════════════════════════════════════════════════════
# UNITS OF MEASURE
# ════════════════════════════════════════════════════════════════════

@router.get("/uoms", summary="List all units of measure")
async def list_uoms(
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    cache_key = "master:uoms"
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content={"success": True, "data": cached})
    svc = MasterDataService(db)
    uoms = await svc.get_uoms()
    data = [UOMOut.model_validate(u).model_dump(mode='json') for u in uoms]
    await cache.set(cache_key, data, ttl=600)
    return ok(data=data)


@router.post(
    "/uoms",
    summary="Create a unit of measure",
    status_code=201,
    dependencies=[require_perm("product.create")],  # type: ignore[list-item]
)
async def create_uom(
    payload: UOMCreate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    from app.db.repositories import UnitOfMeasureRepository
    from app.core.exceptions import AlreadyExistsError
    repo = UnitOfMeasureRepository(db)
    existing = await repo.get_by(uom_code=payload.uom_code.upper())
    if existing:
        raise AlreadyExistsError(f"UOM code '{payload.uom_code}' already exists.")
    uom = await repo.create({**payload.model_dump(), "uom_code": payload.uom_code.upper()})
    await cache.delete("master:uoms")
    return created(data=UOMOut.model_validate(uom).model_dump(mode='json'), message="UOM created.")


@router.patch("/uoms/{uom_id}", summary="Update a UOM")
async def update_uom(
    uom_id: UUID,
    payload: UOMCreate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    from app.db.repositories import UnitOfMeasureRepository
    repo = UnitOfMeasureRepository(db)
    uom = await repo.get_or_raise(uom_id)
    updated = await repo.update(uom, payload.model_dump(exclude_unset=True))
    await cache.delete("master:uoms")
    return ok(data=UOMOut.model_validate(updated).model_dump(mode='json'), message="UOM updated.")


# ════════════════════════════════════════════════════════════════════
# GST RATES
# ════════════════════════════════════════════

@router.get("/gst-rates", summary="List all GST rate slabs")
async def list_gst_rates(
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    cache_key = "master:gst_rates"
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content={"success": True, "data": cached})
    svc = MasterDataService(db)
    rates = await svc.get_gst_rates()
    data = [GSTRateOut.model_validate(r).model_dump(mode='json') for r in rates]
    await cache.set(cache_key, data, ttl=3600)
    return ok(data=data)


# ════════════════════════════════════════════════════════════════════
# HSN / SAC CODES
# ════════════════════════════════════════════════════════════════════

@router.get("/hsn-codes", summary="Search HSN/SAC codes")
async def search_hsn(
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
    q: str = Query(..., min_length=2, description="HSN code prefix or description keyword"),
    limit: int = Query(20, ge=1, le=100),
) -> ORJSONResponse:
    cache_key = cache.cache_key("hsn", q, str(limit))
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content={"success": True, "data": cached})
    svc = MasterDataService(db)
    codes = await svc.search_hsn(q)
    data = [HSNCodeOut.model_validate(c).model_dump() for c in codes[:limit]]
    await cache.set(cache_key, data, ttl=600)
    return ok(data=data)


@router.get("/hsn-codes/{hsn_code}", summary="Get HSN code details")
async def get_hsn(
    hsn_code: str,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import HSNCodeRepository
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.db.models import HSNCode
    stmt = (
        select(HSNCode)
        .where(HSNCode.hsn_code == hsn_code)
        .options(selectinload(HSNCode.gst_rate))
    )
    result = await db.execute(stmt)
    hsn = result.scalar_one_or_none()
    if not hsn:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"HSN code '{hsn_code}' not found.")
    return ok(data=HSNCodeOut.model_validate(hsn).model_dump())


# ════════════════════════════════════════════════════════════════════
# GLOBAL SEARCH
# ════════════════════════════════════════════════════════════════════

@router.get("/search", summary="Global search across customers, vendors, and products")
async def global_search(
    current: CurrentUserDep,
    db: DBDep,
    q: str = Query(..., min_length=2, description="Search term"),
    limit: int = Query(10, ge=1, le=50),
) -> ORJSONResponse:
    from sqlalchemy import select, or_
    from app.db.models import Party, Product

    like = f"%{q}%"

    # Customers
    cust_stmt = (
        select(Party)
        .where(
            Party.company_id == current.company_id,
            Party.is_active == True,
            Party.party_type.in_(["customer", "both"]),
            or_(Party.display_name.ilike(like), Party.phone.ilike(like), Party.gstin.ilike(like)),
        )
        .limit(limit)
    )
    cust_result = await db.execute(cust_stmt)
    customers = cust_result.scalars().all()

    # Vendors
    vend_stmt = (
        select(Party)
        .where(
            Party.company_id == current.company_id,
            Party.is_active == True,
            Party.party_type.in_(["vendor", "both"]),
            or_(Party.display_name.ilike(like), Party.phone.ilike(like)),
        )
        .limit(limit)
    )
    vend_result = await db.execute(vend_stmt)
    vendors = vend_result.scalars().all()

    # Products
    prod_stmt = (
        select(Product)
        .where(
            Product.company_id == current.company_id,
            Product.is_active == True,
            or_(
                Product.product_name.ilike(like),
                Product.product_code.ilike(like),
                Product.barcode.ilike(like),
            ),
        )
        .limit(limit)
    )
    prod_result = await db.execute(prod_stmt)
    products = prod_result.scalars().all()

    return ok(data={
        "customers": [{"id": str(p.id), "name": p.display_name, "type": "customer"} for p in customers],
        "vendors":   [{"id": str(p.id), "name": p.display_name, "type": "vendor"} for p in vendors],
        "products":  [{"id": str(p.id), "name": p.product_name, "code": p.product_code, "type": "product"} for p in products],
    })
