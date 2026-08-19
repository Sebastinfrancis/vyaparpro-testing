"""VyaparPro – Inventory Service Layer"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AlreadyExistsError, BusinessError, NotFoundError
from app.db.models.inventory import (
    StockAdjustmentItem, StockMovement, StockTransferItem, Warehouse,
)
from app.db.repositories.inventory import (
    InventoryStockRepository, ProductBatchRepository, SerialNumberRepository,
    StockAdjustmentRepository, StockMovementRepository,
    StockTransferRepository, WarehouseRepository,
)
from app.schemas.inventory import (
    StockAdjustmentCreate, StockTransferCreate, WarehouseCreate, WarehouseUpdate,
)
from app.db.models import Product


class WarehouseService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = WarehouseRepository(session)

    async def create(self, company_id: UUID, payload: WarehouseCreate, user_id: UUID) -> Warehouse:
        existing = await self.repo.get_by(company_id=company_id, warehouse_code=payload.warehouse_code)
        if existing:
            raise AlreadyExistsError(f"Warehouse code '{payload.warehouse_code}' already exists.")
        if payload.is_default:
            default = await self.repo.get_default(company_id)
            if default:
                await self.repo.update(default, {"is_default": False})
        data = payload.model_dump()
        data["company_id"] = company_id
        return await self.repo.create(data)

    async def list(self, company_id: UUID) -> list[Warehouse]:
        return await self.repo.get_by_company(company_id)


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.stock_repo = InventoryStockRepository(session)
        self.movement_repo = StockMovementRepository(session)
        self.adj_repo = StockAdjustmentRepository(session)
        self.transfer_repo = StockTransferRepository(session)
        self.session = session

    async def record_movement(
        self, company_id: UUID, product_id: UUID, warehouse_id: UUID,
        movement_type: str, quantity: Decimal, cost_price: Decimal = Decimal("0"),
        batch_no: str = "", serial_no: str = "", expiry_date: date | None = None,
        ref_type: str | None = None, ref_id: UUID | None = None,
        ref_no: str | None = None, narration: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
        # Record movement ledger
        self.session.add(StockMovement(
            company_id=company_id, product_id=product_id, warehouse_id=warehouse_id,
            movement_type=movement_type, quantity=quantity, cost_price=cost_price,
            batch_no=batch_no, serial_no=serial_no, expiry_date=expiry_date,
            ref_type=ref_type, ref_id=ref_id, ref_no=ref_no,
            narration=narration, movement_date=date.today(), created_by=user_id,
        ))
        # Update stock balance
        await self.stock_repo.upsert_stock(
            company_id=company_id, product_id=product_id, warehouse_id=warehouse_id,
            batch_no=batch_no or "", serial_no=serial_no or "",
            qty_delta=quantity, cost_price=cost_price, expiry_date=expiry_date,
        )
        product = await self.session.get(Product, product_id)
        if product and product.track_inventory and not product.is_service:
            product.current_stock = (product.current_stock or 0) + int(quantity)
        
        await self.session.flush()

        try:
            from app.api.v1.dependencies import get_cache
            cache = await get_cache()
            await cache.delete_pattern(f"products:{company_id}:*")
        except Exception:
            pass

    async def create_adjustment(self, company_id: UUID, payload: StockAdjustmentCreate, user_id: UUID):
        from app.db.repositories.billing import DocumentSequenceRepository
        seq = DocumentSequenceRepository(self.session)
        adj_no = await seq.next_number(company_id, "adjustment")
        adj = await self.adj_repo.create({
            "company_id": company_id,
            "adjustment_no": adj_no,
            "adjustment_date": payload.adjustment_date,
            "adjustment_type": payload.adjustment_type,
            "warehouse_id": payload.warehouse_id,
            "reason": payload.reason,
            "status": "draft",
            "created_by": user_id,
        })
        for item in payload.items:
            variance = item.physical_qty - item.system_qty
            self.session.add(StockAdjustmentItem(
                adjustment_id=adj.id, product_id=item.product_id,
                batch_no=item.batch_no, serial_no=item.serial_no,
                expiry_date=item.expiry_date, system_qty=item.system_qty,
                physical_qty=item.physical_qty, variance_qty=variance,
                cost_price=item.cost_price, reason=item.reason,
            ))
        await self.session.flush()
        return adj

    async def post_adjustment(self, adj_id: UUID, company_id: UUID, user_id: UUID):
        adj = await self.adj_repo.get_or_raise_scoped(adj_id, company_id=company_id)
        if adj.status != "draft":
            raise BusinessError("Only draft adjustments can be posted.")
        from sqlalchemy import select
        from app.db.models.inventory import StockAdjustmentItem as SAI
        items = (await self.session.execute(
            select(SAI).where(SAI.adjustment_id == adj_id)
        )).scalars().all()
        for item in items:
            if item.variance_qty != 0:
                mtype = "adjustment_in" if item.variance_qty > 0 else "adjustment_out"
                await self.record_movement(
                    company_id=company_id, product_id=item.product_id,
                    warehouse_id=adj.warehouse_id, movement_type=mtype,
                    quantity=item.variance_qty, cost_price=item.cost_price,
                    batch_no=item.batch_no or "", serial_no=item.serial_no or "",
                    expiry_date=item.expiry_date,
                    ref_type="adjustment", ref_id=adj_id, ref_no=adj.adjustment_no,
                    narration=item.reason or adj.reason, user_id=user_id,
                )
        from datetime import datetime, timezone
        await self.adj_repo.update(adj, {
            "status": "posted",
            "posted_at": datetime.now(timezone.utc),
            "approved_by": user_id,
        })

    async def create_transfer(self, company_id: UUID, payload: StockTransferCreate, user_id: UUID):
        from app.db.repositories.billing import DocumentSequenceRepository
        seq = DocumentSequenceRepository(self.session)
        trf_no = await seq.next_number(company_id, "transfer")
        trf = await self.transfer_repo.create({
            "company_id": company_id,
            "transfer_no": trf_no,
            "transfer_date": payload.transfer_date,
            "from_warehouse_id": payload.from_warehouse_id,
            "to_warehouse_id": payload.to_warehouse_id,
            "narration": payload.narration,
            "status": "draft",
            "created_by": user_id,
        })
        for item in payload.items:
            self.session.add(StockTransferItem(
                transfer_id=trf.id, product_id=item.product_id,
                batch_no=item.batch_no, serial_no=item.serial_no,
                transfer_qty=item.transfer_qty, cost_price=item.cost_price,
            ))
        await self.session.flush()
        return trf

    async def dispatch_transfer(self, transfer_id: UUID, company_id: UUID, user_id: UUID):
        trf = await self.transfer_repo.get_or_raise_scoped(transfer_id, company_id=company_id)
        if trf.status != "draft":
            raise BusinessError("Only draft transfers can be dispatched.")
        from sqlalchemy import select
        from app.db.models.inventory import StockTransferItem as STI
        items = (await self.session.execute(
            select(STI).where(STI.transfer_id == transfer_id)
        )).scalars().all()
        for item in items:
            await self.record_movement(
                company_id=company_id, product_id=item.product_id,
                warehouse_id=trf.from_warehouse_id, movement_type="transfer_out",
                quantity=-item.transfer_qty, cost_price=item.cost_price,
                batch_no=item.batch_no or "", serial_no=item.serial_no or "",
                ref_type="transfer", ref_id=transfer_id, ref_no=trf.transfer_no,
                user_id=user_id,
            )
        from datetime import datetime, timezone
        await self.transfer_repo.update(trf, {
            "status": "dispatched",
            "dispatched_at": datetime.now(timezone.utc),
        })

    async def receive_transfer(self, transfer_id: UUID, company_id: UUID, user_id: UUID):
        trf = await self.transfer_repo.get_or_raise_scoped(transfer_id, company_id=company_id)
        if trf.status != "dispatched":
            raise BusinessError("Transfer must be dispatched before receiving.")
        from sqlalchemy import select
        from app.db.models.inventory import StockTransferItem as STI
        items = (await self.session.execute(
            select(STI).where(STI.transfer_id == transfer_id)
        )).scalars().all()
        for item in items:
            await self.record_movement(
                company_id=company_id, product_id=item.product_id,
                warehouse_id=trf.to_warehouse_id, movement_type="transfer_in",
                quantity=item.transfer_qty, cost_price=item.cost_price,
                batch_no=item.batch_no or "", serial_no=item.serial_no or "",
                ref_type="transfer", ref_id=transfer_id, ref_no=trf.transfer_no,
                user_id=user_id,
            )
        from datetime import datetime, timezone
        await self.transfer_repo.update(trf, {
            "status": "received",
            "received_at": datetime.now(timezone.utc),
            "received_by": user_id,
        })

    async def cancel_transfer(self, transfer_id: UUID, company_id: UUID, user_id: UUID):
        trf = await self.transfer_repo.get_or_raise_scoped(transfer_id, company_id=company_id)
        if trf.status not in ("draft",):
            raise BusinessError(
                "Only draft transfers can be cancelled. A dispatched transfer must be "
                "received and then corrected with a reverse transfer."
            )
        await self.transfer_repo.update(trf, {"status": "cancelled"})

    async def get_stock_valuation(self, company_id: UUID) -> dict:
        from sqlalchemy import text
        stmt = text("""
            SELECT p.product_name, p.product_code, p.hsn_code,
                   SUM(s.quantity) AS total_qty,
                   AVG(s.cost_price) AS avg_cost,
                   SUM(s.quantity * s.cost_price) AS stock_value
            FROM inventory_stock s
            JOIN products p ON p.id = s.product_id
            WHERE s.company_id = :cid AND s.quantity > 0
            GROUP BY p.product_name, p.product_code, p.hsn_code
            ORDER BY stock_value DESC
        """)
        rows = (await self.session.execute(stmt, {"cid": str(company_id)})).mappings().all()
        total_value = sum(Decimal(str(r["stock_value"])) for r in rows)
        return {"items": [dict(r) for r in rows], "total_value": str(total_value)}
