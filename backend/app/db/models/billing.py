"""
VyaparPro — Billing ORM Models
Quotation · SalesOrder · PurchaseOrder · JobOrder · WorkOrder ·
DeliveryChallan · Invoice · CreditNote · DebitNote · Payment
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer,
    Numeric, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models import UUIDMixin, TimestampMixin, SoftDeleteMixin


# ════════════════════════════════════════════════════════════════════
# SHARED GST-AMOUNT MIXIN (all billing documents carry these fields)
# ════════════════════════════════════════════════════════════════════

class GSTAmountMixin:
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    cess_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    other_charges: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    round_off: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))


# ════════════════════════════════════════════════════════════════════
# QUOTATIONS
# ════════════════════════════════════════════════════════════════════

class Quotation(Base, UUIDMixin, TimestampMixin, GSTAmountMixin):
    __tablename__ = "quotations"
    __table_args__ = (UniqueConstraint("company_id", "quote_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    quote_no: Mapped[str] = mapped_column(String(30), nullable=False)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    valid_until: Mapped[Optional[date]] = mapped_column(Date)
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    billing_name: Mapped[str] = mapped_column(String(200), nullable=False)
    billing_gstin: Mapped[Optional[str]] = mapped_column(String(15))
    billing_address: Mapped[Optional[str]] = mapped_column(Text)
    billing_state_code: Mapped[Optional[str]] = mapped_column(String(30))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20))
    contact_email: Mapped[Optional[str]] = mapped_column(String(150))
    place_of_supply: Mapped[str] = mapped_column(String(2), default="27")
    supply_type: Mapped[str] = mapped_column(String(20), default="intra")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    tds_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    salesperson_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    payment_terms: Mapped[Optional[str]] = mapped_column(String(50))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    terms_conditions: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft|sent|viewed|accepted|rejected|expired|converted
    converted_to_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    converted_to_so_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    items: Mapped[list["QuotationItem"]] = relationship("QuotationItem", back_populates="quotation", cascade="all, delete-orphan")
    party: Mapped[Optional["Party"]] = relationship("Party", foreign_keys=[party_id])  # type: ignore


class QuotationItem(Base, UUIDMixin):
    __tablename__ = "quotation_items"

    quotation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("1"))
    uom_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("units_of_measure.id"))
    rate: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal("0"))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("18"))
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    cess_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    quotation: Mapped["Quotation"] = relationship("Quotation", back_populates="items")


# ════════════════════════════════════════════════════════════════════
# JOB ORDERS
# ════════════════════════════════════════════════════════════════════

class JobOrder(Base, UUIDMixin, TimestampMixin, GSTAmountMixin):
    __tablename__ = "job_orders"
    __table_args__ = (UniqueConstraint("company_id", "jo_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    jo_no: Mapped[str] = mapped_column(String(30), nullable=False)
    jo_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    billing_name: Mapped[str] = mapped_column(String(200), nullable=False)
    jo_type: Mapped[str] = mapped_column(String(30), default="service")
    # service|manufacturing|repair|installation|amc|project|maintenance|custom
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    scope_of_work: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    # low|normal|high|urgent|critical
    linked_po_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    linked_quote_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id"))
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    expected_completion: Mapped[Optional[date]] = mapped_column(Date)
    actual_completion: Mapped[Optional[date]] = mapped_column(Date)
    estimated_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    advance_received: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    department: Mapped[Optional[str]] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="open")
    # open|in_progress|on_hold|completed|cancelled|invoiced
    completion_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    items: Mapped[list["JobOrderItem"]] = relationship("JobOrderItem", back_populates="job_order", cascade="all, delete-orphan")
    party: Mapped[Optional["Party"]] = relationship("Party", foreign_keys=[party_id])  # type: ignore


class JobOrderItem(Base, UUIDMixin):
    __tablename__ = "job_order_items"

    jo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("job_orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    item_type: Mapped[str] = mapped_column(String(15), default="labour")
    # material|labour|service|overhead|subcontract
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("1"))
    uom_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("units_of_measure.id"))
    rate: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("18"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    issued_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    returned_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    job_order: Mapped["JobOrder"] = relationship("JobOrder", back_populates="items")


# ════════════════════════════════════════════════════════════════════
# PURCHASE ORDERS
# ════════════════════════════════════════════════════════════════════

class PurchaseOrder(Base, UUIDMixin, TimestampMixin, GSTAmountMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("company_id", "po_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    po_no: Mapped[str] = mapped_column(String(30), nullable=False)
    po_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"), nullable=False)
    vendor_ref_no: Mapped[Optional[str]] = mapped_column(String(50))
    linked_jo_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("job_orders.id"))
    linked_quote_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id"))
    deliver_to_warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    delivery_address: Mapped[Optional[str]] = mapped_column(Text)
    expected_delivery: Mapped[Optional[date]] = mapped_column(Date)
    actual_delivery: Mapped[Optional[date]] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1"))
    tds_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    advance_paid: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    payment_terms: Mapped[Optional[str]] = mapped_column(String(50))
    delivery_terms: Mapped[Optional[str]] = mapped_column(String(50))
    warranty_terms: Mapped[Optional[str]] = mapped_column(Text)
    special_instructions: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft|sent|acknowledged|partial|received|closed|cancelled
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    # True = you (the buyer) self-assess and pay this PO's GST directly to the govt
    approval_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending|approved|rejected
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    items: Mapped[list["PurchaseOrderItem"]] = relationship("PurchaseOrderItem", back_populates="po", cascade="all, delete-orphan")
    vendor: Mapped["Party"] = relationship("Party", foreign_keys=[vendor_id])  # type: ignore
    job_order: Mapped[Optional["JobOrder"]] = relationship("JobOrder", foreign_keys=[linked_jo_id])
    grns: Mapped[list["GoodsReceiptNote"]] = relationship("GoodsReceiptNote", back_populates="po")


class PurchaseOrderItem(Base, UUIDMixin):
    __tablename__ = "purchase_order_items"

    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    uom_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("units_of_measure.id"))
    rate: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal("0"))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("18"))
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    returned_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    jo_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("job_order_items.id"))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    cess_amount: Mapped[Decimal] = mapped_column(Numeric(15,2),default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15,2),default=Decimal("0"))
    itc_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    itc_ineligible_reason: Mapped[Optional[str]] = mapped_column(String(50))
    # e.g. 'motor_vehicle' | 'food_beverage' | 'employee_benefit' | 'construction' | 'personal_use' | 'other'

    po: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="items")


# ════════════════════════════════════════════════════════════════════
# GOODS RECEIPT NOTE (GRN)
# ════════════════════════════════════════════════════════════════════

class GoodsReceiptNote(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "goods_receipt_notes"
    __table_args__ = (UniqueConstraint("company_id", "grn_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    grn_no: Mapped[str] = mapped_column(String(30), nullable=False)
    grn_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    vendor_invoice_no: Mapped[Optional[str]] = mapped_column(String(50))
    vendor_invoice_date: Mapped[Optional[date]] = mapped_column(Date)
    quality_status: Mapped[str] = mapped_column(String(20), default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    items: Mapped[list["GRNItem"]] = relationship("GRNItem", back_populates="grn", cascade="all, delete-orphan")
    po: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="grns")


class GRNItem(Base, UUIDMixin):
    __tablename__ = "grn_items"

    grn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("goods_receipt_notes.id", ondelete="CASCADE"), nullable=False)
    po_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_order_items.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    ordered_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    accepted_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    rejected_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    serial_no: Mapped[Optional[str]] = mapped_column(String(80))
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    mfg_date: Mapped[Optional[date]] = mapped_column(Date)
    rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))

    grn: Mapped["GRNItem"] = relationship("GoodsReceiptNote", back_populates="items")


# ════════════════════════════════════════════════════════════════════
# DELIVERY CHALLAN
# ════════════════════════════════════════════════════════════════════

class DeliveryChallan(Base, UUIDMixin, TimestampMixin, GSTAmountMixin):
    __tablename__ = "delivery_challans"
    __table_args__ = (UniqueConstraint("company_id", "dc_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    dc_no: Mapped[str] = mapped_column(String(30), nullable=False)
    dc_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    billing_name: Mapped[str] = mapped_column(String(200), nullable=False)
    billing_address: Mapped[Optional[str]] = mapped_column(Text)
    shipping_name: Mapped[Optional[str]] = mapped_column(String(200))
    shipping_address: Mapped[Optional[str]] = mapped_column(Text)
    challan_type: Mapped[str] = mapped_column(String(30), default="delivery")
    # delivery|returnable|job_work|others
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    vehicle_no: Mapped[Optional[str]] = mapped_column(String(20))
    driver_name: Mapped[Optional[str]] = mapped_column(String(100))
    lrn_no: Mapped[Optional[str]] = mapped_column(String(50))       # lorry receipt number
    ewb_no: Mapped[Optional[str]] = mapped_column(String(20))       # e-way bill
    ewb_valid_till: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    place_of_supply: Mapped[str] = mapped_column(String(2), default="27")
    supply_type: Mapped[str] = mapped_column(String(20), default="intra")
    linked_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    linked_jo_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("job_orders.id"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    items: Mapped[list["DeliveryChallanItem"]] = relationship("DeliveryChallanItem", back_populates="challan", cascade="all, delete-orphan")


class DeliveryChallanItem(Base, UUIDMixin):
    __tablename__ = "delivery_challan_items"

    dc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("delivery_challans.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    uom_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("units_of_measure.id"))
    rate: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    serial_no: Mapped[Optional[str]] = mapped_column(String(80))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    challan: Mapped["DeliveryChallan"] = relationship("DeliveryChallan", back_populates="items")


# ════════════════════════════════════════════════════════════════════
# INVOICE (Sales Tax Invoice + all types)
# ════════════════════════════════════════════════════════════════════

class Invoice(Base, UUIDMixin, TimestampMixin, GSTAmountMixin):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("company_id", "invoice_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    invoice_no: Mapped[str] = mapped_column(String(30), nullable=False)
    invoice_type: Mapped[str] = mapped_column(String(30), default="tax_invoice")
    # tax_invoice|proforma|bill_of_supply|export_invoice|credit_note|debit_note
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    # Billing party
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    billing_name: Mapped[str] = mapped_column(String(200), nullable=False)
    billing_gstin: Mapped[Optional[str]] = mapped_column(String(15))
    billing_address: Mapped[Optional[str]] = mapped_column(Text)
    billing_state_code: Mapped[Optional[str]] = mapped_column(String(30))
    shipping_name: Mapped[Optional[str]] = mapped_column(String(200))
    shipping_address: Mapped[Optional[str]] = mapped_column(Text)
    shipping_state_code: Mapped[Optional[str]] = mapped_column(String(30))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20))
    contact_email: Mapped[Optional[str]] = mapped_column(String(150))
    # JO / PO reference
    jo_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("job_orders.id"))
    jo_no: Mapped[Optional[str]] = mapped_column(String(30))
    po_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"))
    po_no: Mapped[Optional[str]] = mapped_column(String(30))
    po_date: Mapped[Optional[date]] = mapped_column(Date)
    quote_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id"))
    dc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("delivery_challans.id"))
    # GST
    place_of_supply: Mapped[str] = mapped_column(String(2), default="27")
    supply_type: Mapped[str] = mapped_column(String(20), default="intra")
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    # E-Invoice
    irn: Mapped[Optional[str]] = mapped_column(String(64))
    ack_no: Mapped[Optional[str]] = mapped_column(String(20))
    ack_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ewb_no: Mapped[Optional[str]] = mapped_column(String(20))
    ewb_valid_till: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    transporter_name: Mapped[Optional[str]] = mapped_column(String(100))
    transporter_id: Mapped[Optional[str]] = mapped_column(String(20))
    vehicle_no: Mapped[Optional[str]] = mapped_column(String(20))
    qr_code_data: Mapped[Optional[str]] = mapped_column(Text)
    signed_invoice: Mapped[Optional[str]] = mapped_column(Text)
    # Financial
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1"))
    tds_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    tcs_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    # Against (for credit/debit notes)
    against_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"))
    # Misc
    salesperson_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    payment_terms: Mapped[Optional[str]] = mapped_column(String(50))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    terms_conditions: Mapped[Optional[str]] = mapped_column(Text)
    internal_remarks: Mapped[Optional[str]] = mapped_column(Text)
    # Status
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft|finalized|sent|partial|paid|overdue|cancelled|void
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_export: Mapped[bool] = mapped_column(Boolean, default=False)
    export_type: Mapped[Optional[str]] = mapped_column(String(10))  # 'WPAY' or 'WOPAY'
    supply_category: Mapped[str] = mapped_column(String(20), default="taxable")
    # taxable | nil_rated | exempt | non_gst — drives GSTR-1/3B Table 3.1(c)/(e) split

    items: Mapped[list["InvoiceItem"]] = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan", lazy = "selectin",)
    party: Mapped[Optional["Party"]] = relationship("Party", foreign_keys=[party_id])  # type: ignore
    job_order: Mapped[Optional["JobOrder"]] = relationship("JobOrder", foreign_keys=[jo_id])
    purchase_order: Mapped[Optional["PurchaseOrder"]] = relationship("PurchaseOrder", foreign_keys=[po_id])
    payments: Mapped[list["PaymentAllocation"]] = relationship("PaymentAllocation", back_populates="invoice")


class InvoiceItem(Base, UUIDMixin):
    __tablename__ = "invoice_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(8))
    sac_code: Mapped[Optional[str]] = mapped_column(String(6))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("1"))
    uom_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("units_of_measure.id"))
    rate: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal("0"))
    mrp: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("18"))
    cgst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("9"))
    sgst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("9"))
    igst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    cess_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    serial_no: Mapped[Optional[str]] = mapped_column(String(80))
    jo_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("job_order_items.id"))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="items")


# ════════════════════════════════════════════════════════════════════
# PAYMENTS
# ════════════════════════════════════════════════════════════════════

class Payment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("company_id", "payment_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    payment_no: Mapped[str] = mapped_column(String(30), nullable=False)
    payment_type: Mapped[str] = mapped_column(String(15), nullable=False)  # receipt|payment|contra|journal
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), default="cash")
    # cash|bank_transfer|cheque|upi|neft|rtgs|credit_card|debit_card|other
    cheque_no: Mapped[Optional[str]] = mapped_column(String(20))
    cheque_date: Mapped[Optional[date]] = mapped_column(Date)
    bank_ref_no: Mapped[Optional[str]] = mapped_column(String(50))
    upi_ref_no: Mapped[Optional[str]] = mapped_column(String(50))
    gateway_txn_id: Mapped[Optional[str]] = mapped_column(String(100))
    narration: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    allocations: Mapped[list["PaymentAllocation"]] = relationship("PaymentAllocation", back_populates="payment", cascade="all, delete-orphan")


class PaymentAllocation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "payment_allocations"

    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"))
    ref_type: Mapped[str] = mapped_column(String(20), nullable=False)   # invoice|advance|jo
    ref_no: Mapped[Optional[str]] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    payment: Mapped["Payment"] = relationship("Payment", back_populates="allocations")
    invoice: Mapped[Optional["Invoice"]] = relationship("Invoice", back_populates="payments")


# ════════════════════════════════════════════════════════════════════
# DOCUMENT SEQUENCES
# ════════════════════════════════════════════════════════════════════

class DocumentSequence(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "document_sequences"
    __table_args__ = (UniqueConstraint("company_id", "branch_id", "doc_type", "financial_year"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # invoice|po|jo|payment|grn|dc|quote|adjustment|transfer
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    suffix: Mapped[Optional[str]] = mapped_column(String(20))
    current_no: Mapped[int] = mapped_column(Integer, default=0)
    pad_length: Mapped[int] = mapped_column(SmallInteger, default=4)
    financial_year: Mapped[Optional[str]] = mapped_column(String(7))  # '2025-26'
    reset_on_fy: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ════════════════════════════════════════════════════════════════════
# E-INVOICE LOG
# ════════════════════════════════════════════════════════════════════

class EInvoiceLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "einvoice_log"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    invoice_no: Mapped[Optional[str]] = mapped_column(String(30))
    request_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    response_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    irn: Mapped[Optional[str]] = mapped_column(String(64))
    ack_no: Mapped[Optional[str]] = mapped_column(String(20))
    ack_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    signed_invoice: Mapped[Optional[str]] = mapped_column(Text)
    qr_code: Mapped[Optional[str]] = mapped_column(Text)
    cancel_irn: Mapped[Optional[str]] = mapped_column(String(64))
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(10))
    cancel_remarks: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
