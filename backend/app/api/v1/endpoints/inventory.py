"""
Inventory / Warehouse API — the backend for branch-wise stock.

Every branch gets one or more "warehouses" (stock points). Stock is tracked
per warehouse in `inventory_stock`, movements are logged in `stock_movements`,
and stock is moved between branches via `stock_transfers`.

GET    /warehouses                              — list warehouses (optional ?branch_id=)
POST   /warehouses                               — create a warehouse for a branch
PATCH  /warehouses/{id}                          — update a warehouse
DELETE /warehouses/{id}                          — deactivate a warehouse

GET    /inventory/stock                          — current stock (optional ?warehouse_id=&product_id=)
GET    /inventory/branch-stock-matrix            — per-branch stock for all products, or one product/branch
GET    /inventory/low-stock                      — products at/below reorder level
GET    /inventory/expiring                       — batches expiring soon (?days=30)
GET    /inventory/valuation                       — total stock value + breakdown

POST   /inventory/adjustments                    — create a stock adjustment (draft)
GET    /inventory/adjustments                    — list adjustments
POST   /inventory/adjustments/{id}/post           — post adjustment (applies stock movements)

POST   /inventory/transfers                       — create inter-branch transfer (draft)
GET    /inventory/transfers                        — list transfers
GET    /inventory/transfers/{id}                   — get one transfer with items
POST   /inventory/transfers/{id}/dispatch           — dispatch (stock leaves source branch)
POST   /inventory/transfers/{id}/receive            — receive (stock lands in dest branch)
POST   /inventory/transfers/{id}/cancel             — cancel a draft transfer
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse

from app.api.v1.dependencies import CurrentUserDep, DBDep, PaginationDep, require_perm
from app.core.exceptions import BusinessError
from app.schemas.inventory import (
    ProductBatchOut, SerialNumberOut, StockAdjustmentCreate, StockAdjustmentOut,
    StockMovementOut, StockOut, StockTransferCreate, StockTransferOut,
    WarehouseCreate, WarehouseOut, WarehouseUpdate,
)
from app.services.inventory import InventoryService, WarehouseService
from app.utils.responses import created, ok, paginated

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# WAREHOUSES (branch stock points)
# ═══════════════════════════════════════════════════════════════════

@router.get("/warehouses", summary="List warehouses / branch stock points", dependencies=[require_perm("warehouse.read")])
async def list_warehouses(
    current: CurrentUserDep,
    db: DBDep,
    branch_id: UUID | None = Query(None, description="Filter to a single branch"),
    active_only: bool = Query(True),
) -> ORJSONResponse:
    svc = WarehouseService(db)
    warehouses = await svc.list(current.company_id)
    if branch_id:
        warehouses = [w for w in warehouses if w.branch_id == branch_id]
    if active_only:
        warehouses = [w for w in warehouses if w.is_active]
    return ok(data=[WarehouseOut.model_validate(w).model_dump(mode="json") for w in warehouses])


@router.post(
    "/warehouses", summary="Create a warehouse / stock point", status_code=201,
    dependencies=[require_perm("warehouse.create")],  # type: ignore[list-item]
)
async def create_warehouse(
    payload: WarehouseCreate, current: CurrentUserDep, db: DBDep,
) -> ORJSONResponse:
    svc = WarehouseService(db)
    wh = await svc.create(current.company_id, payload, current.user_id)
    return created(data=WarehouseOut.model_validate(wh).model_dump(mode="json"), message="Warehouse created.")


@router.patch(
    "/warehouses/{warehouse_id}", summary="Update a warehouse",
    dependencies=[require_perm("warehouse.update")],  # type: ignore[list-item]
)
async def update_warehouse(
    warehouse_id: UUID, payload: WarehouseUpdate, current: CurrentUserDep, db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories.inventory import WarehouseRepository
    repo = WarehouseRepository(db)
    wh = await repo.get_or_raise_scoped(warehouse_id, company_id=current.company_id)
    wh = await repo.update(wh, payload.model_dump(exclude_unset=True))
    return ok(data=WarehouseOut.model_validate(wh).model_dump(mode="json"), message="Warehouse updated.")


@router.delete(
    "/warehouses/{warehouse_id}", summary="Deactivate a warehouse",
    dependencies=[require_perm("warehouse.delete")],  # type: ignore[list-item]
)
async def delete_warehouse(
    warehouse_id: UUID, current: CurrentUserDep, db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories.inventory import WarehouseRepository
    repo = WarehouseRepository(db)
    wh = await repo.get_or_raise_scoped(warehouse_id, company_id=current.company_id)
    await repo.update(wh, {"is_active": False})
    return ok(message="Warehouse deactivated.")


# ═══════════════════════════════════════════════════════════════════
# STOCK
# ═══════════════════════════════════════════════════════════════════

@router.get(
    "/inventory/stock", summary="Current stock balances",
    dependencies=[require_perm("inventory.read")],  # type: ignore[list-item]
)
async def get_stock(
    current: CurrentUserDep,
    db: DBDep,
    warehouse_id: UUID | None = Query(None),
    product_id: UUID | None = Query(None),
) -> ORJSONResponse:
    from app.db.repositories.inventory import InventoryStockRepository
    repo = InventoryStockRepository(db)
    rows = await repo.get_stock(current.company_id, product_id=product_id, warehouse_id=warehouse_id)
    return ok(data=[StockOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get(
    "/inventory/branch-stock-matrix",
    summary="Stock quantity per branch — for products x branches, or one product's branch split",
    dependencies=[require_perm("inventory.read")],  # type: ignore[list-item]
)
async def get_branch_stock_matrix(
    current: CurrentUserDep,
    db: DBDep,
    product_id: UUID | None = Query(None, description="Limit to one product (for row-level breakdown)"),
    branch_id: UUID | None = Query(None, description="Limit to one branch (for the branch filter dropdown)"),
) -> ORJSONResponse:
    from sqlalchemy import text

    # A branch-scoped user can only ever see their own branch's numbers —
    # matches the same rule used for /branches and /inventory/low-stock.
    bid = branch_id
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = current.branch_id

    stmt = text("""
        SELECT p.id AS product_id, p.product_name, p.product_code, p.reorder_level,
               b.id AS branch_id, b.branch_name, b.branch_code,
               COALESCE(SUM(s.quantity), 0) AS quantity,
               COALESCE(SUM(s.quantity * s.cost_price), 0) AS stock_value
        FROM products p
        CROSS JOIN branches b
        LEFT JOIN warehouses w ON w.branch_id = b.id AND w.company_id = p.company_id AND w.is_active = TRUE
        LEFT JOIN inventory_stock s ON s.product_id = p.id AND s.warehouse_id = w.id
        WHERE p.company_id = :cid AND b.company_id = :cid
          AND p.is_active = TRUE AND b.is_active = TRUE
          AND (CAST(:product_id AS uuid) IS NULL OR p.id = :product_id)
          AND (CAST(:branch_id AS uuid) IS NULL OR b.id = :branch_id)
        GROUP BY p.id, p.product_name, p.product_code, p.reorder_level, b.id, b.branch_name, b.branch_code
        ORDER BY p.product_name, b.branch_name
    """)
    rows = (await db.execute(stmt, {
        "cid": str(current.company_id),
        "product_id": str(product_id) if product_id else None,
        "branch_id": str(bid) if bid else None,
    })).mappings().all()

    return ok(data=[
        {
            "product_id": str(r["product_id"]), "product_name": r["product_name"],
            "product_code": r["product_code"], "reorder_level": str(r["reorder_level"]) if r["reorder_level"] is not None else None,
            "branch_id": str(r["branch_id"]), "branch_name": r["branch_name"], "branch_code": r["branch_code"],
            "quantity": str(r["quantity"]), "stock_value": str(r["stock_value"]),
        }
        for r in rows
    ])


@router.get(
    "/inventory/low-stock", summary="Products at/below reorder level",
    dependencies=[require_perm("inventory.read")],  # type: ignore[list-item]
)
async def get_low_stock(
    current: CurrentUserDep, db: DBDep,
    branch_id: UUID | None = Query(None, description="Filter to one branch — omit for company-wide"),
) -> ORJSONResponse:
    from app.db.repositories.inventory import InventoryStockRepository
    bid = branch_id
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = current.branch_id
    repo = InventoryStockRepository(db)
    rows = await repo.get_low_stock(current.company_id, branch_id=bid)
    return ok(data=rows)


@router.get(
    "/inventory/expiring", summary="Batches expiring soon",
    dependencies=[require_perm("inventory.read")],  # type: ignore[list-item]
)
async def get_expiring(
    current: CurrentUserDep, db: DBDep, days: int = Query(30, ge=1, le=365),
) -> ORJSONResponse:
    from app.db.repositories.inventory import InventoryStockRepository
    repo = InventoryStockRepository(db)
    rows = await repo.get_expiring_soon(current.company_id, days=days)
    return ok(data=[StockOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get(
    "/inventory/valuation", summary="Total stock value + product breakdown",
    dependencies=[require_perm("inventory.read")],  # type: ignore[list-item]
)
async def get_valuation(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = InventoryService(db)
    result = await svc.get_stock_valuation(current.company_id)
    return ok(data=result)


# ═══════════════════════════════════════════════════════════════════
# STOCK ADJUSTMENTS
# ═══════════════════════════════════════════════════════════════════

@router.post(
    "/inventory/adjustments", summary="Create a stock adjustment (draft)", status_code=201,
    dependencies=[require_perm("inventory.adjust")],  # type: ignore[list-item]
)
async def create_adjustment(
    payload: StockAdjustmentCreate, current: CurrentUserDep, db: DBDep,
) -> ORJSONResponse:
    from app.api.v1.dependencies import assert_warehouse_branch_access
    await assert_warehouse_branch_access(db, current, payload.warehouse_id)
    svc = InventoryService(db)
    adj = await svc.create_adjustment(current.company_id, payload, current.user_id)
    return created(data=StockAdjustmentOut.model_validate(adj).model_dump(mode="json"), message="Adjustment created as draft.")


@router.get(
    "/inventory/adjustments", summary="List stock adjustments",
    dependencies=[require_perm("inventory.read")],  # type: ignore[list-item]
)
async def list_adjustments(current: CurrentUserDep, db: DBDep, pg: PaginationDep) -> ORJSONResponse:
    from app.db.repositories.inventory import StockAdjustmentRepository
    repo = StockAdjustmentRepository(db)
    result = await repo.search(current.company_id, page=pg.page, page_size=pg.page_size)
    items = [StockAdjustmentOut.model_validate(a).model_dump(mode="json") for a in result.items]
    return paginated(items=items, total=result.total, page=result.page, page_size=result.page_size, pages=result.pages)


@router.post(
    "/inventory/adjustments/{adjustment_id}/post", summary="Post an adjustment (applies stock movements)",
    dependencies=[require_perm("inventory.adjust")],  # type: ignore[list-item]
)
async def post_adjustment(
    adjustment_id: UUID, current: CurrentUserDep, db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories.inventory import StockAdjustmentRepository
    from app.api.v1.dependencies import assert_warehouse_branch_access
    adj = await StockAdjustmentRepository(db).get_or_raise_scoped(adjustment_id, company_id=current.company_id)
    await assert_warehouse_branch_access(db, current, adj.warehouse_id)
    svc = InventoryService(db)
    await svc.post_adjustment(adjustment_id, current.company_id, current.user_id)
    return ok(message="Adjustment posted — stock updated.")


# ═══════════════════════════════════════════════════════════════════
# INTER-BRANCH STOCK TRANSFERS
# ═══════════════════════════════════════════════════════════════════

@router.post(
    "/inventory/transfers", summary="Create an inter-branch stock transfer (draft)", status_code=201,
    dependencies=[require_perm("inventory.transfer")],  # type: ignore[list-item]
)
async def create_transfer(
    payload: StockTransferCreate, current: CurrentUserDep, db: DBDep,
) -> ORJSONResponse:
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise BusinessError("Source and destination warehouse must be different.")
    from app.api.v1.dependencies import assert_warehouse_branch_access
    # A branch-scoped user may only send stock OUT of their own branch —
    # receiving is a separate, explicit action gated at /receive instead.
    await assert_warehouse_branch_access(db, current, payload.from_warehouse_id)
    svc = InventoryService(db)
    trf = await svc.create_transfer(current.company_id, payload, current.user_id)
    return created(data=StockTransferOut.model_validate(trf).model_dump(mode="json"), message="Transfer created as draft.")


@router.get(
    "/inventory/transfers", summary="List stock transfers",
    dependencies=[require_perm("inventory.read")],  # type: ignore[list-item]
)
async def list_transfers(current: CurrentUserDep, db: DBDep, pg: PaginationDep) -> ORJSONResponse:
    from app.db.repositories.inventory import StockTransferRepository
    repo = StockTransferRepository(db)
    result = await repo.search(current.company_id, page=pg.page, page_size=pg.page_size)
    items = [StockTransferOut.model_validate(t).model_dump(mode="json") for t in result.items]
    return paginated(items=items, total=result.total, page=result.page, page_size=result.page_size, pages=result.pages)


@router.get(
    "/inventory/transfers/{transfer_id}", summary="Get transfer with line items",
    dependencies=[require_perm("inventory.read")],  # type: ignore[list-item]
)
async def get_transfer(transfer_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.inventory import StockTransferRepository
    repo = StockTransferRepository(db)
    trf = await repo.get_or_raise_scoped(transfer_id, company_id=current.company_id)
    data = StockTransferOut.model_validate(trf).model_dump(mode="json")
    data["items"] = [
        {
            "id": str(i.id), "product_id": str(i.product_id),
            "batch_no": i.batch_no, "serial_no": i.serial_no,
            "transfer_qty": str(i.transfer_qty), "received_qty": str(i.received_qty),
            "cost_price": str(i.cost_price),
        }
        for i in trf.items
    ]
    return ok(data=data)


@router.post(
    "/inventory/transfers/{transfer_id}/dispatch", summary="Dispatch a transfer (stock leaves source)",
    dependencies=[require_perm("inventory.transfer")],  # type: ignore[list-item]
)
async def dispatch_transfer(transfer_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.inventory import StockTransferRepository
    from app.api.v1.dependencies import assert_warehouse_branch_access
    trf = await StockTransferRepository(db).get_or_raise_scoped(transfer_id, company_id=current.company_id)
    await assert_warehouse_branch_access(db, current, trf.from_warehouse_id)
    svc = InventoryService(db)
    await svc.dispatch_transfer(transfer_id, current.company_id, current.user_id)
    return ok(message="Transfer dispatched — stock deducted from source branch.")


@router.post(
    "/inventory/transfers/{transfer_id}/receive", summary="Receive a transfer (stock lands at destination)",
    dependencies=[require_perm("inventory.transfer_receive")],  # type: ignore[list-item]
)
async def receive_transfer(transfer_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.inventory import StockTransferRepository
    from app.api.v1.dependencies import assert_warehouse_branch_access
    trf = await StockTransferRepository(db).get_or_raise_scoped(transfer_id, company_id=current.company_id)
    await assert_warehouse_branch_access(db, current, trf.to_warehouse_id)
    svc = InventoryService(db)
    await svc.receive_transfer(transfer_id, current.company_id, current.user_id)
    return ok(message="Transfer received — stock added to destination branch.")


@router.post(
    "/inventory/transfers/{transfer_id}/cancel", summary="Cancel a draft transfer",
    dependencies=[require_perm("inventory.transfer")],  # type: ignore[list-item]
)
async def cancel_transfer(transfer_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.inventory import StockTransferRepository
    from app.api.v1.dependencies import assert_warehouse_branch_access
    trf = await StockTransferRepository(db).get_or_raise_scoped(transfer_id, company_id=current.company_id)
    await assert_warehouse_branch_access(db, current, trf.from_warehouse_id)
    svc = InventoryService(db)
    await svc.cancel_transfer(transfer_id, current.company_id, current.user_id)
    return ok(message="Transfer cancelled.")