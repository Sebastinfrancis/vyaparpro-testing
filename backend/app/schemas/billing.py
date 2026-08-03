"""VyaparPro – Billing Pydantic Schemas"""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID
from pydantic import Field, model_validator
from app.schemas import APIModel
from datetime import datetime


class BillingItemIn(APIModel):
    product_id: Optional[UUID] = None
    description: str = Field(max_length=300)
    hsn_code: Optional[str] = None
    sac_code: Optional[str] = None
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    uom_id: Optional[UUID] = None
    rate: Decimal = Field(default=Decimal("0"), ge=0)
    mrp: Optional[Decimal] = None
    discount_pct: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    gst_rate: Decimal = Decimal("18")
    cess_rate: Decimal = Decimal("0")
    warehouse_id: Optional[UUID] = None
    batch_no: Optional[str] = None
    serial_no: Optional[str] = None
    jo_item_id: Optional[UUID] = None
    display_order: int = 0
    itc_eligible: bool = True
    itc_ineligible_reason: Optional[str] = None


class BillingItemOut(APIModel):
    id: UUID
    product_id: Optional[UUID] = None
    description: str
    hsn_code: Optional[str] = None
    quantity: Decimal
    received_qty: Decimal = Decimal("0")
    rate: Decimal
    mrp: Optional[Decimal] = None
    discount_pct: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    gst_rate: Decimal
    cgst_rate: Decimal = Decimal("0")
    sgst_rate: Decimal = Decimal("0")
    igst_rate: Decimal = Decimal("0")
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    total_amount: Decimal
    batch_no: Optional[str] = None
    serial_no: Optional[str] = None
    display_order: int


# ── Quotation ─────────────────────────────────────────────────────

class QuotationCreate(APIModel):
    quote_date: date
    valid_until: Optional[date] = None
    party_id: Optional[UUID] = None
    billing_name: str = Field(max_length=200)
    billing_gstin: Optional[str] = None
    billing_address: Optional[str] = None
    billing_state_code: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    place_of_supply: str = "27"
    supply_type: str = "intra"
    currency: str = "INR"
    warehouse_id: Optional[UUID] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    terms_conditions: Optional[str] = None
    other_charges: Decimal = Decimal("0")
    tds_amount: Decimal = Decimal("0")
    items: list[BillingItemIn] = Field(min_length=1)


class QuotationUpdate(APIModel):
    valid_until: Optional[date] = None
    billing_name: Optional[str] = None
    billing_address: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    items: Optional[list[BillingItemIn]] = None


class QuotationOut(APIModel):
    id: UUID
    company_id: UUID
    quote_no: str
    quote_date: date
    valid_until: Optional[date]
    party_id: Optional[UUID]
    billing_name: str
    billing_gstin: Optional[str]
    billing_address: Optional[str]
    place_of_supply: str
    supply_type: str
    subtotal: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    other_charges: Decimal
    total_amount: Decimal
    status: str
    notes: Optional[str]
    created_at: datetime
    items: list[BillingItemOut] = []


# ── Job Order ─────────────────────────────────────────────────────

class JobOrderCreate(APIModel):
    jo_date: date
    party_id: Optional[UUID] = None
    billing_name: str = Field(max_length=200)
    jo_type: str = "service"
    title: str = Field(max_length=200)
    description: Optional[str] = None
    scope_of_work: Optional[str] = None
    priority: str = "normal"
    linked_po_id: Optional[UUID] = None
    linked_quote_id: Optional[UUID] = None
    start_date: Optional[date] = None
    expected_completion: Optional[date] = None
    estimated_amount: Decimal = Decimal("0")
    assigned_to: Optional[UUID] = None
    other_charges: Decimal = Decimal("0")
    notes: Optional[str] = None
    items: list[BillingItemIn] = Field(min_length=1)


class JobOrderUpdate(APIModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    completion_pct: Optional[Decimal] = None
    actual_completion: Optional[date] = None
    assigned_to: Optional[UUID] = None
    notes: Optional[str] = None
    items: Optional[list[BillingItemIn]] = None


class JobOrderOut(APIModel):
    id: UUID
    company_id: UUID
    jo_no: str
    jo_date: date
    party_id: Optional[UUID]
    billing_name: str
    jo_type: str
    title: str
    description: Optional[str]
    priority: str
    linked_po_id: Optional[UUID]
    start_date: Optional[date]
    expected_completion: Optional[date]
    actual_completion: Optional[date]
    estimated_amount: Decimal
    subtotal: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    status: str
    completion_pct: Decimal
    notes: Optional[str]
    created_at: datetime
    items: list[BillingItemOut] = []


# ── Purchase Order ────────────────────────────────────────────────

class PurchaseOrderCreate(APIModel):
    po_date: date
    vendor_id: UUID
    vendor_ref_no: Optional[str] = None
    linked_jo_id: Optional[UUID] = None
    deliver_to_warehouse_id: Optional[UUID] = None
    expected_delivery: Optional[date] = None
    currency: str = "INR"
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    special_instructions: Optional[str] = None
    notes: Optional[str] = None
    other_charges: Decimal = Decimal("0")
    tds_amount: Decimal = Decimal("0")
    supply_type: str = "intra"  # intra | inter — determines CGST+SGST vs IGST
    reverse_charge: bool = False
    items: list[BillingItemIn] = Field(min_length=1)


class PurchaseOrderUpdate(APIModel):
    status: Optional[str] = None
    expected_delivery: Optional[date] = None
    notes: Optional[str] = None
    items: Optional[list[BillingItemIn]] = None

class PurchaseOrderItemOut(APIModel):
    id: UUID
    product_id: Optional[UUID] = None
    description: str
    hsn_code: Optional[str] = None
    quantity: Decimal
    rate: Decimal
    discount_pct: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    gst_rate: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    amount: Decimal
    received_qty: Decimal
    returned_qty: Decimal
    itc_eligible: bool = True
    itc_ineligible_reason: Optional[str] = None
    display_order: int


class PurchaseOrderOut(APIModel):
    id: UUID
    company_id: UUID
    po_no: str
    po_date: date
    vendor_id: UUID
    vendor_ref_no: Optional[str]
    linked_jo_id: Optional[UUID]
    expected_delivery: Optional[date]
    actual_delivery: Optional[date]
    subtotal: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    status: str
    reverse_charge: bool = False
    approval_status: str
    notes: Optional[str]
    created_at: datetime
    items: list[PurchaseOrderItemOut] = []


# ── Delivery Challan ─────────────────────────────────────────────

class DeliveryChallanCreate(APIModel):
    dc_date: date
    party_id: Optional[UUID] = None
    billing_name: str = Field(max_length=200)
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    challan_type: str = "delivery"
    warehouse_id: Optional[UUID] = None
    vehicle_no: Optional[str] = None
    place_of_supply: str = "27"
    supply_type: str = "intra"
    linked_jo_id: Optional[UUID] = None
    notes: Optional[str] = None
    items: list[BillingItemIn] = Field(min_length=1)


class DeliveryChallanOut(APIModel):
    id: UUID
    company_id: UUID
    dc_no: str
    dc_date: date
    billing_name: str
    challan_type: str
    vehicle_no: Optional[str]
    ewb_no: Optional[str]
    total_amount: Decimal
    status: str
    created_at: datetime
    items: list[BillingItemOut] = []


# ── Invoice ───────────────────────────────────────────────────────

class InvoiceCreate(APIModel):
    invoice_type: str = "tax_invoice"
    invoice_date: date
    due_date: Optional[date] = None
    party_id: Optional[UUID] = None
    against_invoice_id: Optional[UUID] = None
    billing_name: str = Field(max_length=200)
    billing_gstin: Optional[str] = None
    billing_address: Optional[str] = None
    billing_state_code: Optional[str] = None
    shipping_name: Optional[str] = None
    shipping_address: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    jo_id: Optional[UUID] = None
    jo_no: Optional[str] = None
    po_id: Optional[UUID] = None
    po_no: Optional[str] = None
    po_date: Optional[date] = None
    quote_id: Optional[UUID] = None
    dc_id: Optional[UUID] = None
    against_invoice_id: Optional[UUID] = None
    place_of_supply: str = "27"
    supply_type: str = "intra"
    reverse_charge: bool = False
    currency: str = "INR"
    is_export: bool = False
    export_type: Optional[str] = None
    supply_category: str = "taxable"  # taxable | nil_rated | exempt | non_gst
    warehouse_id: Optional[UUID] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    terms_conditions: Optional[str] = None
    other_charges: Decimal = Decimal("0")
    tds_amount: Decimal = Decimal("0")
    tcs_amount: Decimal = Decimal("0")
    round_off: Decimal = Decimal("0")
    items: list[BillingItemIn] = Field(min_length=1)


class InvoiceUpdate(APIModel):
    # Always editable regardless of status
    due_date: Optional[date] = None
    notes: Optional[str] = None

    # Only applied by the service when the invoice is still a draft
    invoice_date: Optional[date] = None
    invoice_type: Optional[str] = None
    party_id: Optional[UUID] = None
    billing_name: Optional[str] = None
    billing_gstin: Optional[str] = None
    billing_address: Optional[str] = None
    billing_state_code: Optional[str] = None
    shipping_name: Optional[str] = None
    shipping_address: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    place_of_supply: Optional[str] = None
    supply_type: Optional[str] = None
    payment_terms: Optional[str] = None
    terms_conditions: Optional[str] = None
    other_charges: Optional[Decimal] = None
    tds_amount: Optional[Decimal] = None
    tcs_amount: Optional[Decimal] = None
    supply_category: Optional[str] = None
    round_off: Optional[Decimal] = None
    items: Optional[list[BillingItemIn]] = None


class InvoiceCancelRequest(APIModel):
    reason: str = Field(min_length=5)


class InvoiceOut(APIModel):
    id: UUID
    company_id: UUID
    invoice_no: str
    invoice_type: str
    invoice_date: date
    due_date: Optional[date]
    party_id: Optional[UUID]
    against_invoice_id: Optional[UUID] = None 
    billing_name: str
    billing_gstin: Optional[str]
    billing_address: Optional[str]
    billing_state_code: Optional[str]
    shipping_address: Optional[str]
    contact_phone: Optional[str]
    contact_email: Optional[str]
    jo_id: Optional[UUID]
    jo_no: Optional[str]
    po_id: Optional[UUID]
    po_no: Optional[str]
    po_date: Optional[date]
    place_of_supply: str
    supply_type: str
    reverse_charge: bool
    irn: Optional[str]
    ack_no: Optional[str]
    ewb_no: Optional[str]
    qr_code_data: Optional[str]
    transporter_id: Optional[str] = None
    vehicle_no: Optional[str] = None
    currency: str
    is_export: bool = False
    export_type: Optional[str] = None
    supply_category: str = "taxable"
    subtotal: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    other_charges: Decimal
    tds_amount: Decimal
    tcs_amount: Decimal
    round_off: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    status: str
    finalized_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    items: list[BillingItemOut] = []


# ── Payment ───────────────────────────────────────────────────────

class PaymentCreate(APIModel):
    payment_type: str  # receipt|payment
    payment_date: date
    party_id: Optional[UUID] = None
    amount: Decimal = Field(gt=0)
    payment_method: str = "cash"
    cheque_no: Optional[str] = None
    cheque_date: Optional[date] = None
    bank_ref_no: Optional[str] = None
    upi_ref_no: Optional[str] = None
    gateway_txn_id: Optional[str] = None
    narration: Optional[str] = None
    allocations: list[dict] = Field(default_factory=list)
    # [{"invoice_id": "...", "amount": 1000}]


class PaymentOut(APIModel):
    id: UUID
    company_id: UUID
    payment_no: str
    payment_type: str
    payment_date: date
    party_id: Optional[UUID]
    amount: Decimal
    payment_method: str
    cheque_no: Optional[str]
    bank_ref_no: Optional[str]
    upi_ref_no: Optional[str]
    narration: Optional[str]
    status: str
    created_at: datetime

class EInvoiceRecordIn(APIModel):
    irn: Optional[str] = Field(None, min_length=10, max_length=64)
    ack_no: Optional[str] = None
    ack_date: Optional[datetime] = None
    qr_code_data: Optional[str] = None
    ewb_no: Optional[str] = None
    ewb_valid_till: Optional[datetime] = None
    transporter_id: Optional[str] = None
    vehicle_no: Optional[str] = None
