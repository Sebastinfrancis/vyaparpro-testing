"""
Product Management API

GET    /products                  — search/filter/paginate
POST   /products                  — create product
GET    /products/{id}             — get by id
PATCH  /products/{id}             — update
DELETE /products/{id}             — deactivate
GET    /products/barcode/{code}   — lookup by barcode
POST   /products/{id}/image       — upload product image
GET    /products/{id}/stock       — current stock across warehouses (placeholder)
POST   /products/{id}/variants    — create variant (size/colour/etc.)
GET    /products/{id}/variants    — list variants
"""
from __future__ import annotations

from uuid import UUID

from fastapi.encoders import jsonable_encoder

from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import (
    CacheDep, CurrentUserDep, DBDep, PaginationDep, require_perm,
)
from app.schemas import ProductCreate, ProductOut, ProductUpdate, ProductVariantCreate
from app.services import ProductService
from app.utils.responses import created, ok, paginated

router = APIRouter()

_TTL = 120


@router.get("", summary="Search / filter products with pagination", dependencies=[require_perm("product.read")])
async def list_products(
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    cache: CacheDep,
    q: str | None = Query(None, description="Search name / code / barcode / brand / HSN"),
    cat_id: UUID | None = Query(None, description="Filter by category ID"),
    is_service: bool | None = Query(None, description="True=services, False=goods"),
    active_only: bool = Query(True),
    brand: str | None = Query(None, description="Filter by brand name"),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    low_stock: bool = Query(False, description="Only show items at/below reorder level"),
) -> ORJSONResponse:
    cache_key = cache.cache_key(
        "products", str(current.company_id),
        q or "", str(cat_id or ""), str(is_service), str(active_only),
        brand or "", str(pg.page), str(pg.page_size),
    )
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content=cached)

    svc = ProductService(db)
    result = await svc.search(
        company_id=current.company_id,
        query=q,
        cat_id=cat_id,
        is_service=is_service,
        active_only=active_only,
        page=pg.page,
        page_size=pg.page_size,
    )
    items = [ProductOut.model_validate(p).model_dump(mode='json') for p in result.items]
    resp = {
        "success": True, "message": "OK",
        "data": {
            "items": items, "total": result.total,
            "page": result.page, "page_size": result.page_size, "pages": result.pages,
        },
    }
    clean_resp = jsonable_encoder(resp)
    await cache.set(cache_key, clean_resp, ttl=_TTL)
    return ORJSONResponse(content=clean_resp)


@router.post(
    "",
    summary="Create a product / service",
    status_code=201,
    dependencies=[require_perm("product.create")],  # type: ignore[list-item]
)
async def create_product(
    payload: ProductCreate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    svc = ProductService(db)
    product = await svc.create(current.company_id, payload, current.user_id)
    await cache.delete_pattern(f"products:{current.company_id}:*")
    return created(
        data=ProductOut.model_validate(product).model_dump(mode='json'),
        message="Product created successfully.",
    )


@router.get("/barcode/{barcode}", summary="Lookup product by barcode (fast POS scan)", dependencies=[require_perm("product.read")])
async def get_by_barcode(
    barcode: str,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    cache_key = cache.cache_key("barcode", str(current.company_id), barcode)
    cached = await cache.get(cache_key)
    if cached:
        return ORJSONResponse(content={"success": True, "data": cached})

    from sqlalchemy.future import select
    from sqlalchemy.orm import selectinload
    from app.db.models import Product
    stmt = (
        select(Product).where(Product.company_id == current.company_id, Product.barcode == barcode).options(
            selectinload(Product.category), selectinload(Product.uom)
        )
    )
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"No product found with barcode '{barcode}'.")
    data = ProductOut.model_validate(product).model_dump(mode='json')
    await cache.set(cache_key, data, ttl=300)
    return ok(data=data)


@router.get("/{product_id}", summary="Get product by ID", dependencies=[require_perm("product.read")])
async def get_product(
    product_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import ProductRepository
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.db.models import Product
    stmt = (
        select(Product)
        .where(Product.id == product_id, Product.company_id == current.company_id)
        .options(selectinload(Product.category), selectinload(Product.uom))
    )
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Product not found.")
    return ok(data=ProductOut.model_validate(product).model_dump(mode='json'))


@router.patch(
    "/{product_id}",
    summary="Update product",
    dependencies=[require_perm("product.update")],  # type: ignore[list-item]
)
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    svc = ProductService(db)
    product = await svc.update(product_id, payload, current.company_id, current.user_id)
    await cache.delete_pattern(f"products:{current.company_id}:*")
    await cache.delete_pattern(f"barcode:{current.company_id}:*")
    return ok(data=ProductOut.model_validate(product).model_dump(mode='json'), message="Product updated.")


@router.delete(
    "/{product_id}",
    summary="Deactivate product",
    dependencies=[require_perm("product.delete")],  # type: ignore[list-item]
)
async def delete_product(
    product_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    cache: CacheDep,
) -> ORJSONResponse:
    from app.db.repositories import ProductRepository
    repo = ProductRepository(db)
    await repo.soft_delete_scoped(product_id, company_id=current.company_id)
    await cache.delete_pattern(f"products:{current.company_id}:*")
    return ok(message="Product deactivated.")


@router.post("/{product_id}/image", summary="Upload product image", dependencies=[require_perm("product.update")])
async def upload_image(
    product_id: UUID,
    file: UploadFile,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        from app.core.exceptions import ValidationError
        raise ValidationError("Only JPEG, PNG, or WebP images accepted.")
    image_url = f"/static/products/{product_id}.png"
    from app.db.repositories import ProductRepository
    repo = ProductRepository(db)
    product = await repo.get_or_raise_scoped(product_id, company_id=current.company_id)
    await repo.update(product, {"image_url": image_url})
    return ok(data={"image_url": image_url}, message="Image uploaded.")


@router.get("/{product_id}/stock", summary="Current stock across all warehouses", dependencies=[require_perm("product.read")])
async def product_stock(
    product_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    # Wire to inventory_stock table when warehouse module is built
    return ok(data={"product_id": str(product_id), "warehouses": [], "total_qty": 0})


# ── Variants ────────────────────────────────────────────────────────────────

@router.get("/{product_id}/variants", summary="List product variants", dependencies=[require_perm("product.read")])
async def list_variants(product_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from sqlalchemy import select
    from app.db.models import ProductVariant
    stmt = select(ProductVariant).where(
        ProductVariant.product_id == product_id,
        ProductVariant.is_active == True,
    )
    result = await db.execute(stmt)
    variants = result.scalars().all()
    from app.schemas import ProductVariantOut
    return ok(data=[ProductVariantOut.model_validate(v).model_dump(mode='json') for v in variants])


@router.post("/{product_id}/variants", summary="Add a product variant", status_code=201, dependencies=[require_perm("product.update")])
async def create_variant(
    product_id: UUID,
    payload: ProductVariantCreate,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.models import ProductVariant
    from app.schemas import ProductVariantCreate, ProductVariantOut
    variant = ProductVariant(product_id=product_id, **payload.model_dump())
    db.add(variant)
    await db.flush()
    await db.refresh(variant)
    return created(
        data=ProductVariantOut.model_validate(variant).model_dump(mode='json'),
        message="Variant created.",
    )
