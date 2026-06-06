"""VyaparPro – Inventory Repositories"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from uuid import UUID
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import selectinload
from app.db.models.inventory import (
    BarcodeLabel, InventoryStock, ProductBatch, SerialNumber,
    StockAdjustment, StockMovement, StockTransfer, Warehouse, WarehouseZone,
)
from app.db.repositories.base import BaseRepository, Pagination


class WarehouseRepository(BaseRepository[Warehouse]):
    model = Warehouse

    async def get_by_company(self, company_id: UUID, active_only: bool = True) -> list[Warehouse]:
        stmt = (select(Warehouse).where(Warehouse.company_id == company_id)
                .options(selectinload(Warehouse.zones)))
        if active_only:
            stmt = stmt.where(Warehouse.is_active == True)
        stmt = stmt.order_by(Warehouse.warehouse_name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_default(self, company_id: UUID) -> Warehouse | None:
        return await self.get_by(company_id=company_id, is_default=True)


class InventoryStockRepository(BaseRepository[InventoryStock]):
    model = InventoryStock

    async def get_stock(self, company_id: UUID, product_id: UUID | None = None,
                        warehouse_id: UUID | None = None) -> list[InventoryStock]:
        stmt = select(InventoryStock).where(InventoryStock.company_id == company_id)
        if product_id:
            stmt = stmt.where(InventoryStock.product_id == product_id)
        if warehouse_id:
            stmt = stmt.where(InventoryStock.warehouse_id == warehouse_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_low_stock(self, company_id: UUID) -> list[dict]:
        stmt = text("""
            SELECT s.product_id, p.product_name, p.product_code, p.reorder_level,
                   SUM(s.quantity) AS total_qty, SUM(s.available_qty) AS available_qty
            FROM inventory_stock s
            JOIN products p ON p.id = s.product_id
            WHERE s.company_id = :cid AND p.track_inventory = TRUE
            GROUP BY s.product_id, p.product_name, p.product_code, p.reorder_level
            HAVING SUM(s.quantity) <= p.reorder_level
            ORDER BY p.product_name
        """)
        rows = (await self.session.execute(stmt, {"cid": str(company_id)})).mappings().all()
        return [dict(r) for r in rows]

    async def get_expiring_soon(self, company_id: UUID, days: int = 30) -> list[InventoryStock]:
        from datetime import timedelta
        cutoff = date.today() + timedelta(days=days)
        stmt = (select(InventoryStock)
                .where(InventoryStock.company_id == company_id,
                       InventoryStock.expiry_date.isnot(None),
                       InventoryStock.expiry_date <= cutoff,
                       InventoryStock.quantity > 0))
        return list((await self.session.execute(stmt)).scalars().all())

    async def upsert_stock(self, company_id: UUID, product_id: UUID, warehouse_id: UUID,
                           batch_no: str, serial_no: str, qty_delta: Decimal,
                           cost_price: Decimal, expiry_date: date | None = None) -> InventoryStock:
        existing = await self.get_by(product_id=product_id, warehouse_id=warehouse_id,
                                     batch_no=batch_no, serial_no=serial_no)
        if existing:
            new_qty = existing.quantity + qty_delta
            return await self.update(existing, {"quantity": new_qty, "last_updated": func.now()})
        return await self.create({"company_id": company_id, "product_id": product_id,
                                  "warehouse_id": warehouse_id, "batch_no": batch_no,
                                  "serial_no": serial_no, "quantity": qty_delta,
                                  "cost_price": cost_price, "expiry_date": expiry_date})


class StockMovementRepository(BaseRepository[StockMovement]):
    model = StockMovement

    async def get_product_history(self, company_id: UUID, product_id: UUID,
                                  from_date: date | None = None, to_date: date | None = None,
                                  page: int = 1, page_size: int = 50) -> Pagination:
        stmt = (select(StockMovement).where(StockMovement.company_id == company_id,
                                            StockMovement.product_id == product_id)
                .order_by(StockMovement.movement_date.desc()))
        if from_date:
            stmt = stmt.where(StockMovement.movement_date >= from_date)
        if to_date:
            stmt = stmt.where(StockMovement.movement_date <= to_date)
        return await self.paginate(stmt, page, page_size)


class StockAdjustmentRepository(BaseRepository[StockAdjustment]):
    model = StockAdjustment

    async def search(self, company_id: UUID, page: int = 1, page_size: int = 20) -> Pagination:
        stmt = (select(StockAdjustment).where(StockAdjustment.company_id == company_id)
                .options(selectinload(StockAdjustment.items))
                .order_by(StockAdjustment.adjustment_date.desc()))
        return await self.paginate(stmt, page, page_size)


class StockTransferRepository(BaseRepository[StockTransfer]):
    model = StockTransfer

    async def search(self, company_id: UUID, page: int = 1, page_size: int = 20) -> Pagination:
        stmt = (select(StockTransfer).where(StockTransfer.company_id == company_id)
                .options(selectinload(StockTransfer.items))
                .order_by(StockTransfer.transfer_date.desc()))
        return await self.paginate(stmt, page, page_size)


class ProductBatchRepository(BaseRepository[ProductBatch]):
    model = ProductBatch

    async def get_by_product(self, company_id: UUID, product_id: UUID) -> list[ProductBatch]:
        stmt = (select(ProductBatch).where(ProductBatch.company_id == company_id,
                                           ProductBatch.product_id == product_id,
                                           ProductBatch.is_active == True)
                .order_by(ProductBatch.expiry_date.asc()))
        return list((await self.session.execute(stmt)).scalars().all())


class SerialNumberRepository(BaseRepository[SerialNumber]):
    model = SerialNumber

    async def get_by_product(self, company_id: UUID, product_id: UUID,
                             status: str | None = None) -> list[SerialNumber]:
        stmt = select(SerialNumber).where(SerialNumber.company_id == company_id,
                                          SerialNumber.product_id == product_id)
        if status:
            stmt = stmt.where(SerialNumber.status == status)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_serial(self, company_id: UUID, serial_no: str) -> SerialNumber | None:
        stmt = select(SerialNumber).where(SerialNumber.company_id == company_id,
                                          SerialNumber.serial_no == serial_no)
        return (await self.session.execute(stmt)).scalar_one_or_none()
