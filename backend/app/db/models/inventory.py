"""
VyaparPro — Inventory ORM Models
Warehouses · Zones · Stock · Movements · Batch · Serial · Transfer · Adjustment
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models import UUIDMixin, TimestampMixin, SoftDeleteMixin


# ════════════════════════════════════════════════════════════════════
# WAREHOUSES & ZONES
# ════════════════════════════════════════════════════════════════════

class Warehouse(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("company_id", "warehouse_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    warehouse_code: Mapped[str] = mapped_column(String(20), nullable=False)
    warehouse_name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(80))
    state: Mapped[Optional[str]] = mapped_column(String(80))
    pincode: Mapped[Optional[str]] = mapped_column(String(10))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    capacity_sqft: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    warehouse_type: Mapped[str] = mapped_column(String(20), default="owned",
        server_default="owned")  # owned|leased|consignment|virtual

    zones: Mapped[list["WarehouseZone"]] = relationship("WarehouseZone", back_populates="warehouse", cascade="all, delete-orphan")
    stock: Mapped[list["InventoryStock"]] = relationship("InventoryStock", back_populates="warehouse")


class WarehouseZone(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "warehouse_zones"
    __table_args__ = (UniqueConstraint("warehouse_id", "zone_code"),)

    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False)
    zone_code: Mapped[str] = mapped_column(String(20), nullable=False)
    zone_name: Mapped[str] = mapped_column(String(60), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(20), default="storage")  # storage|picking|staging|quarantine|returns
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    warehouse: Mapped["Warehouse"] = relationship("Warehouse", back_populates="zones")


# ════════════════════════════════════════════════════════════════════
# INVENTORY STOCK (current balances)
# ════════════════════════════════════════════════════════════════════

class InventoryStock(Base, UUIDMixin):
    """
    Current stock balance per product per warehouse per batch/serial.
    Updated by triggers/service on every stock movement.
    """
    __tablename__ = "inventory_stock"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", "batch_no", "serial_no",
                         name="uq_stock_product_warehouse_batch_serial"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    zone_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouse_zones.id"))
    batch_no: Mapped[str] = mapped_column(String(50), default="", server_default="")
    serial_no: Mapped[str] = mapped_column(String(80), default="", server_default="")
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    mfg_date: Mapped[Optional[date]] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    reserved_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    cost_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    valuation_method: Mapped[str] = mapped_column(String(10), default="FIFO")  # FIFO|LIFO|WAC|SPECIFIC
    barcode: Mapped[Optional[str]] = mapped_column(String(100))          # product/batch barcode
    qr_data: Mapped[Optional[str]] = mapped_column(Text)                  # JSON for QR code
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])  # type: ignore
    warehouse: Mapped["Warehouse"] = relationship("Warehouse", back_populates="stock")

    @property
    def available_qty(self) -> Decimal:
        return self.quantity - self.reserved_qty


# ════════════════════════════════════════════════════════════════════
# STOCK MOVEMENTS (ledger — append-only)
# ════════════════════════════════════════════════════════════════════

class StockMovement(Base, UUIDMixin, TimestampMixin):
    """Immutable ledger of every stock-affecting transaction."""
    __tablename__ = "stock_movements"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    zone_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouse_zones.id"))
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # opening|purchase|sale|transfer_in|transfer_out|return_in|return_out
    # adjustment_in|adjustment_out|production_in|production_out
    # jo_issue|jo_return|damage|expiry|opening_balance
    ref_type: Mapped[Optional[str]] = mapped_column(String(30))   # invoice|purchase_bill|jo|transfer|adjustment
    ref_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    ref_no: Mapped[Optional[str]] = mapped_column(String(50))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)  # +IN / -OUT
    cost_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    serial_no: Mapped[Optional[str]] = mapped_column(String(80))
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    mfg_date: Mapped[Optional[date]] = mapped_column(Date)
    narration: Mapped[Optional[str]] = mapped_column(Text)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])  # type: ignore
    warehouse: Mapped["Warehouse"] = relationship("Warehouse")


# ════════════════════════════════════════════════════════════════════
# STOCK ADJUSTMENTS
# ════════════════════════════════════════════════════════════════════

class StockAdjustment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "stock_adjustments"
    __table_args__ = (UniqueConstraint("company_id", "adjustment_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    adjustment_no: Mapped[str] = mapped_column(String(30), nullable=False)
    adjustment_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    adjustment_type: Mapped[str] = mapped_column(String(20), default="physical_count")
    # physical_count|damage|expiry|theft|correction|opening_balance
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|submitted|approved|posted
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    items: Mapped[list["StockAdjustmentItem"]] = relationship("StockAdjustmentItem", back_populates="adjustment", cascade="all, delete-orphan")
    warehouse: Mapped["Warehouse"] = relationship("Warehouse")


class StockAdjustmentItem(Base, UUIDMixin):
    __tablename__ = "stock_adjustment_items"

    adjustment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stock_adjustments.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    serial_no: Mapped[Optional[str]] = mapped_column(String(80))
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    system_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))   # book stock
    physical_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0")) # actual counted
    variance_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0")) # physical - system
    cost_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    adjustment: Mapped["StockAdjustment"] = relationship("StockAdjustment", back_populates="items")
    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])  # type: ignore


# ════════════════════════════════════════════════════════════════════
# INTER-WAREHOUSE TRANSFERS
# ════════════════════════════════════════════════════════════════════

class StockTransfer(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "stock_transfers"
    __table_args__ = (UniqueConstraint("company_id", "transfer_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    transfer_no: Mapped[str] = mapped_column(String(30), nullable=False)
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False)
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft|dispatched|in_transit|received|cancelled
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    narration: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    received_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    items: Mapped[list["StockTransferItem"]] = relationship("StockTransferItem", back_populates="transfer", cascade="all, delete-orphan")
    from_warehouse: Mapped["Warehouse"] = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped["Warehouse"] = relationship("Warehouse", foreign_keys=[to_warehouse_id])


class StockTransferItem(Base, UUIDMixin):
    __tablename__ = "stock_transfer_items"

    transfer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    serial_no: Mapped[Optional[str]] = mapped_column(String(80))
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    transfer_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    received_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    cost_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))

    transfer: Mapped["StockTransfer"] = relationship("StockTransfer", back_populates="items")
    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])  # type: ignore


# ════════════════════════════════════════════════════════════════════
# BATCH TRACKING
# ════════════════════════════════════════════════════════════════════

class ProductBatch(Base, UUIDMixin, TimestampMixin):
    """Master batch record — created on first purchase/production."""
    __tablename__ = "product_batches"
    __table_args__ = (UniqueConstraint("product_id", "batch_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(50), nullable=False)
    mfg_date: Mapped[Optional[date]] = mapped_column(Date)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    quantity_produced: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    cost_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    barcode: Mapped[Optional[str]] = mapped_column(String(100))
    qr_code_data: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])  # type: ignore


# ════════════════════════════════════════════════════════════════════
# SERIAL NUMBER TRACKING
# ════════════════════════════════════════════════════════════════════

class SerialNumber(Base, UUIDMixin, TimestampMixin):
    """Individual serial number lifecycle tracking."""
    __tablename__ = "serial_numbers"
    __table_args__ = (UniqueConstraint("product_id", "serial_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    serial_no: Mapped[str] = mapped_column(String(80), nullable=False)
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(20), default="in_stock")
    # in_stock|sold|returned|damaged|scrapped|transferred
    purchase_date: Mapped[Optional[date]] = mapped_column(Date)
    sale_date: Mapped[Optional[date]] = mapped_column(Date)
    purchase_ref_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    sale_ref_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    sold_to_party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    warranty_months: Mapped[Optional[int]] = mapped_column(SmallInteger)
    warranty_expiry: Mapped[Optional[date]] = mapped_column(Date)
    barcode: Mapped[Optional[str]] = mapped_column(String(100))
    qr_code_data: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])  # type: ignore


# ════════════════════════════════════════════════════════════════════
# BARCODE / QR LABEL REGISTRY
# ════════════════════════════════════════════════════════════════════

class BarcodeLabel(Base, UUIDMixin, TimestampMixin):
    """Generated barcode/QR labels for printing."""
    __tablename__ = "barcode_labels"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    label_type: Mapped[str] = mapped_column(String(20), nullable=False)  # product|batch|serial|location
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    barcode_value: Mapped[str] = mapped_column(String(200), nullable=False)
    barcode_type: Mapped[str] = mapped_column(String(20), default="CODE128")  # CODE128|EAN13|QR|DATAMATRIX
    qr_data: Mapped[Optional[str]] = mapped_column(Text)
    label_data: Mapped[dict] = mapped_column(JSONB, default=dict)         # full label payload
    print_count: Mapped[int] = mapped_column(Integer, default=0)
    last_printed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
