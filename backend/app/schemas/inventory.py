"""VyaparPro – Inventory Pydantic Schemas"""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import Field
from app.schemas import APIModel


class WarehouseCreate(APIModel):
    warehouse_code: str = Field(max_length=20)
    warehouse_name: str = Field(max_length=100)
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    is_default: bool = False
    warehouse_type: str = "owned"
    capacity_sqft: Optional[Decimal] = None
    branch_id: Optional[UUID] = None


class WarehouseUpdate(APIModel):
    warehouse_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class WarehouseZoneOut(APIModel):
    id: UUID
    zone_code: str
    zone_name: str
    zone_type: str
    is_active: bool


class WarehouseOut(APIModel):
    id: UUID
    company_id: UUID
    warehouse_code: str
    warehouse_name: str
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    pincode: Optional[str]
    is_default: bool
    warehouse_type: str
    is_active: bool
    created_at: datetime
    zones: list[WarehouseZoneOut] = []


class StockOut(APIModel):
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    batch_no: str
    serial_no: str
    expiry_date: Optional[date]
    mfg_date: Optional[date]
    quantity: Decimal
    reserved_qty: Decimal
    available_qty: Decimal
    cost_price: Decimal
    valuation_method: str
    last_updated: datetime


class AdjustmentItemIn(APIModel):
    product_id: UUID
    batch_no: Optional[str] = None
    serial_no: Optional[str] = None
    expiry_date: Optional[date] = None
    system_qty: Decimal = Decimal("0")
    physical_qty: Decimal = Decimal("0")
    cost_price: Decimal = Decimal("0")
    reason: Optional[str] = None


class StockAdjustmentCreate(APIModel):
    adjustment_date: date
    adjustment_type: str = "physical_count"
    warehouse_id: UUID
    reason: Optional[str] = None
    items: list[AdjustmentItemIn] = Field(min_length=1)


class StockAdjustmentOut(APIModel):
    id: UUID
    company_id: UUID
    adjustment_no: str
    adjustment_date: date
    adjustment_type: str
    warehouse_id: UUID
    reason: Optional[str]
    status: str
    created_at: datetime


class TransferItemIn(APIModel):
    product_id: UUID
    batch_no: Optional[str] = None
    serial_no: Optional[str] = None
    transfer_qty: Decimal
    cost_price: Decimal = Decimal("0")


class StockTransferCreate(APIModel):
    transfer_date: date
    from_warehouse_id: UUID
    to_warehouse_id: UUID
    narration: Optional[str] = None
    items: list[TransferItemIn] = Field(min_length=1)


class StockTransferOut(APIModel):
    id: UUID
    company_id: UUID
    transfer_no: str
    transfer_date: date
    from_warehouse_id: UUID
    to_warehouse_id: UUID
    status: str
    narration: Optional[str]
    created_at: datetime


class ProductBatchOut(APIModel):
    id: UUID
    product_id: UUID
    batch_no: str
    mfg_date: Optional[date]
    expiry_date: Optional[date]
    cost_price: Decimal
    barcode: Optional[str]
    is_active: bool


class SerialNumberOut(APIModel):
    id: UUID
    product_id: UUID
    serial_no: str
    batch_no: Optional[str]
    warehouse_id: Optional[UUID]
    status: str
    purchase_date: Optional[date]
    sale_date: Optional[date]
    warranty_expiry: Optional[date]
    barcode: Optional[str]


class StockMovementOut(APIModel):
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    movement_type: str
    ref_type: Optional[str]
    ref_no: Optional[str]
    quantity: Decimal
    cost_price: Optional[Decimal]
    batch_no: Optional[str]
    serial_no: Optional[str]
    narration: Optional[str]
    movement_date: date
    created_at: datetime
