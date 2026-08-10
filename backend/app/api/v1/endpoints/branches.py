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
) -> ORJSONResponse:
    from app.db.repositories import BranchRepository
    repo = BranchRepository(db)
    await repo.soft_delete(branch_id)
    return ok(message="Branch deactivated.")

@router.get("/{branch_id}/dashboard", summary="Branch performance dashboard (real stock + sales figures)")
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


@router.get("/{branch_id}/stock", summary="Live stock at this branch (all warehouses)")
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
