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


@router.get("", summary="List all branches for a company", dependencies=[require_perm("branch.read")])
async def list_branches(
    company_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = BranchService(db)
    branches = await svc.list_by_company(company_id)  # includes user_count — gap #7
    # A branch-scoped user only needs to see (and pick from) their own branch —
    # showing every branch would let them select one they can't transact for anyway.
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        branches = [b for b in branches if b.id == current.branch_id]
    return ok(data=[BranchOut.model_validate(b).model_dump(mode='json') for b in branches])


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
    return created(data=BranchOut.model_validate(branch).model_dump(mode='json'), message="Branch created.")


@router.get("/compare", summary="Target vs actual sales — every branch, side by side", dependencies=[require_perm("branch.read")])
async def compare_branches(
    company_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    """Gap #5 — dashboard had actuals but no target field or branch-vs-branch
    comparison view. Pulls each branch's monthly_target against its real MTD
    sales figure, live from billing."""
    from sqlalchemy import text
    svc = BranchService(db)
    branches = await svc.list_by_company(company_id)

    stmt = text("""
        SELECT branch_id,
               COALESCE(SUM(total_amount) FILTER (
                   WHERE invoice_date >= date_trunc('month', CURRENT_DATE)
               ), 0) AS sales_mtd
        FROM invoices
        WHERE company_id = :cid AND status != 'cancelled' AND branch_id IS NOT NULL
        GROUP BY branch_id
    """)
    rows = (await db.execute(stmt, {"cid": str(company_id)})).mappings().all()
    sales_by_branch = {r["branch_id"]: r["sales_mtd"] for r in rows}

    data = []
    for b in branches:
        actual = sales_by_branch.get(b.id, 0)
        target = b.monthly_target or 0
        achievement_pct = round(float(actual) / float(target) * 100, 1) if target else None
        data.append({
            "branch_id": str(b.id),
            "branch_name": b.branch_name,
            "monthly_target": str(target),
            "sales_mtd": str(actual),
            "achievement_pct": achievement_pct,
        })
    return ok(data=data)


@router.get("/{branch_id}", summary="Get branch by ID", dependencies=[require_perm("branch.read")])
async def get_branch(
    company_id: UUID,
    branch_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = BranchService(db)
    branch = await svc.get_with_user_count(branch_id, company_id)  # gap #7
    return ok(data=BranchOut.model_validate(branch).model_dump(mode='json'))


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
    return ok(data=BranchOut.model_validate(branch).model_dump(mode='json'), message="Branch updated.")


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
    force: bool = False,
) -> ORJSONResponse:
    # Gap #8 — real safety checks: refuses if open stock, pending invoices,
    # or active staff are still tied to this branch, unless force=true.
    svc = BranchService(db)
    await svc.deactivate(branch_id, company_id, current.user_id, force=force)
    return ok(message="Branch deactivated.")

@router.get("/{branch_id}/dashboard", summary="Branch performance dashboard (real stock + sales figures)", dependencies=[require_perm("branch.read")])
async def branch_dashboard(
    company_id: UUID,
    branch_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    """
    Aggregates everything a branch manager needs at a glance:
    stock value/count across the branch's warehouses, today's & MTD sales,
    outstanding receivables, low-stock alerts and recent invoices —
    all pulled live from billing + inventory, not hardcoded.
    """
    from sqlalchemy import text
    from app.db.repositories import BranchRepository

    branch_repo = BranchRepository(db)
    branch = await branch_repo.get_or_raise(branch_id)

    # Stock value + product count across every warehouse tied to this branch
    stock_stmt = text("""
        SELECT COUNT(DISTINCT s.product_id) AS product_count,
               COALESCE(SUM(s.quantity), 0) AS total_units,
               COALESCE(SUM(s.quantity * s.cost_price), 0) AS stock_value
        FROM inventory_stock s
        JOIN warehouses w ON w.id = s.warehouse_id
        WHERE w.branch_id = :bid AND s.quantity > 0
    """)
    stock_row = (await db.execute(stock_stmt, {"bid": str(branch_id)})).mappings().one()

    # Low stock count (reorder level breached) for products held at this branch
    low_stock_stmt = text("""
        SELECT COUNT(*) AS low_stock_count FROM (
            SELECT s.product_id
            FROM inventory_stock s
            JOIN warehouses w ON w.id = s.warehouse_id
            JOIN products p ON p.id = s.product_id
            WHERE w.branch_id = :bid AND p.track_inventory = TRUE
            GROUP BY s.product_id, p.reorder_level
            HAVING SUM(s.quantity) <= p.reorder_level
        ) sub
    """)
    low_stock_row = (await db.execute(low_stock_stmt, {"bid": str(branch_id)})).mappings().one()

    # Sales performance for this branch (today / month-to-date)
    sales_stmt = text("""
        SELECT
            COALESCE(SUM(total_amount) FILTER (WHERE invoice_date = CURRENT_DATE), 0) AS sales_today,
            COALESCE(SUM(total_amount) FILTER (
                WHERE invoice_date >= date_trunc('month', CURRENT_DATE)
            ), 0) AS sales_mtd,
            COUNT(*) FILTER (
                WHERE invoice_date >= date_trunc('month', CURRENT_DATE)
            ) AS invoice_count_mtd,
            COALESCE(SUM(total_amount - paid_amount) FILTER (
                WHERE status IN ('finalized','sent','partial','overdue')
            ), 0) AS pending_receivables
        FROM invoices
        WHERE company_id = :cid AND branch_id = :bid AND status != 'cancelled'
    """)
    sales_row = (await db.execute(sales_stmt, {"cid": str(company_id), "bid": str(branch_id)})).mappings().one()

    # Recent invoices raised from this branch
    recent_stmt = text("""
        SELECT invoice_no, billing_name, invoice_date, total_amount, status
        FROM invoices
        WHERE company_id = :cid AND branch_id = :bid
        ORDER BY invoice_date DESC, created_at DESC
        LIMIT 5
    """)
    recent_rows = (await db.execute(recent_stmt, {"cid": str(company_id), "bid": str(branch_id)})).mappings().all()

    return ok(data={
        "branch": BranchOut.model_validate(branch).model_dump(mode="json"),
        "product_count": stock_row["product_count"],
        "total_units": str(stock_row["total_units"]),
        "stock_value": str(stock_row["stock_value"]),
        "low_stock_count": low_stock_row["low_stock_count"],
        "sales_today": str(sales_row["sales_today"]),
        "sales_mtd": str(sales_row["sales_mtd"]),
        "invoice_count_mtd": sales_row["invoice_count_mtd"],
        "pending_receivables": str(sales_row["pending_receivables"]),
        "recent_invoices": [
            {
                "invoice_no": r["invoice_no"], "party": r["billing_name"],
                "date": r["invoice_date"].isoformat() if r["invoice_date"] else None,
                "amount": str(r["total_amount"]), "status": r["status"],
            }
            for r in recent_rows
        ],
    })


@router.get("/{branch_id}/stock", summary="Live stock at this branch (all warehouses)", dependencies=[require_perm("branch.read")])
async def branch_stock(
    company_id: UUID,
    branch_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from sqlalchemy import text
    stmt = text("""
        SELECT s.product_id, p.product_name, p.product_code, p.hsn_code,
               w.id AS warehouse_id, w.warehouse_name,
               SUM(s.quantity) AS quantity, AVG(s.cost_price) AS cost_price,
               SUM(s.quantity * s.cost_price) AS stock_value
        FROM inventory_stock s
        JOIN warehouses w ON w.id = s.warehouse_id
        JOIN products p ON p.id = s.product_id
        WHERE w.branch_id = :bid AND s.quantity > 0
        GROUP BY s.product_id, p.product_name, p.product_code, p.hsn_code, w.id, w.warehouse_name
        ORDER BY p.product_name
    """)
    rows = (await db.execute(stmt, {"bid": str(branch_id)})).mappings().all()
    return ok(data=[
        {
            "product_id": str(r["product_id"]), "product_name": r["product_name"],
            "product_code": r["product_code"], "hsn_code": r["hsn_code"],
            "warehouse_id": str(r["warehouse_id"]), "warehouse_name": r["warehouse_name"],
            "quantity": str(r["quantity"]), "cost_price": str(r["cost_price"] or 0),
            "stock_value": str(r["stock_value"] or 0),
        }
        for r in rows
    ])



@router.get("/{branch_id}/stock-aging", summary="Stock aging / dead-stock report for this branch", dependencies=[require_perm("branch.read")])
async def branch_stock_aging(
    company_id: UUID,
    branch_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    """Gap #6 — current stock was visible but not how long it's been sitting.
    Buckets every stock line by days since its last movement
    (inventory_stock.last_updated, touched on every purchase/sale/transfer)."""
    from sqlalchemy import text
    stmt = text("""
        SELECT s.product_id, p.product_name, p.product_code,
               w.id AS warehouse_id, w.warehouse_name,
               s.quantity, s.cost_price, s.last_updated,
               (CURRENT_DATE - s.last_updated::date) AS days_since_movement
        FROM inventory_stock s
        JOIN warehouses w ON w.id = s.warehouse_id
        JOIN products p ON p.id = s.product_id
        WHERE w.branch_id = :bid AND s.quantity > 0
        ORDER BY days_since_movement DESC
    """)
    rows = (await db.execute(stmt, {"bid": str(branch_id)})).mappings().all()

    buckets = {"0_30": [], "31_60": [], "61_90": [], "90_plus": []}
    for r in rows:
        days = r["days_since_movement"] or 0
        bucket = "0_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "90_plus"
        buckets[bucket].append({
            "product_id": str(r["product_id"]), "product_name": r["product_name"],
            "product_code": r["product_code"], "warehouse_name": r["warehouse_name"],
            "quantity": str(r["quantity"]), "days_since_movement": days,
            "stock_value": str((r["quantity"] or 0) * (r["cost_price"] or 0)),
        })

    summary = {
        k: {
            "item_count": len(v),
            "stock_value": str(sum(float(i["stock_value"]) for i in v)),
        }
        for k, v in buckets.items()
    }
    return ok(data={"summary": summary, "buckets": buckets})
