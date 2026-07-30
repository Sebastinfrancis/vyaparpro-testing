"""
VyaparPro — SQLAlchemy ORM Models
Complete models for all ERP entities.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    Integer, Numeric, SmallInteger, String, Text, UniqueConstraint,
    func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.utcnow()


# ── Mixins ───────────────────────────────────────────────────────────────────

class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid, server_default=text("uuid_generate_v4()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ═══════════════════════════════════════════════════════════════════
# SECTION 1: ORGANIZATION & COMPANY
# ═══════════════════════════════════════════════════════════════════

class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_type: Mapped[str] = mapped_column(String(30), default="company")
    parent_org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    companies: Mapped[list["Company"]] = relationship("Company", back_populates="organization")
    parent: Mapped[Optional["Organization"]] = relationship("Organization", remote_side="Organization.id")


class Company(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "companies"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade_name: Mapped[Optional[str]] = mapped_column(String(200))
    gstin: Mapped[Optional[str]] = mapped_column(String(15), unique=True)
    pan: Mapped[Optional[str]] = mapped_column(String(10))
    tan: Mapped[Optional[str]] = mapped_column(String(10))
    cin: Mapped[Optional[str]] = mapped_column(String(21))
    business_type: Mapped[str] = mapped_column(String(30), default="retailer")
    reg_address: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(String(150))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    website: Mapped[Optional[str]] = mapped_column(String(200))
    logo_url: Mapped[Optional[str]] = mapped_column(Text)
    financial_year_start: Mapped[int] = mapped_column(SmallInteger, default=4)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    country: Mapped[str] = mapped_column(String(2), default="IN")
    state_code: Mapped[Optional[str]] = mapped_column(String(2))
    invoice_prefix: Mapped[str] = mapped_column(String(20), default="INV-")
    po_prefix: Mapped[str] = mapped_column(String(20), default="PO-")
    jo_prefix: Mapped[str] = mapped_column(String(20), default="JO-")
    quote_prefix: Mapped[str] = mapped_column(String(20), default="QT-")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))

    organization: Mapped["Organization"] = relationship("Organization", back_populates="companies")
    branches: Mapped[list["Branch"]] = relationship("Branch", back_populates="company")
    users: Mapped[list["User"]] = relationship("User", back_populates="company")
    roles: Mapped[list["Role"]] = relationship("Role", back_populates="company")


class Branch(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("company_id", "branch_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_code: Mapped[str] = mapped_column(String(20), nullable=False)
    branch_name: Mapped[str] = mapped_column(String(150), nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(15))
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(80))
    state: Mapped[Optional[str]] = mapped_column(String(80))
    state_code: Mapped[Optional[str]] = mapped_column(String(2))
    pincode: Mapped[Optional[str]] = mapped_column(String(10))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(150))
    branch_type: Mapped[str] = mapped_column(String(20), default="branch")

    company: Mapped["Company"] = relationship("Company", back_populates="branches")
    users: Mapped[list["User"]] = relationship("User", back_populates="branch")


# ═══════════════════════════════════════════════════════════════════
# SECTION 2: USERS & PERMISSIONS
# ═══════════════════════════════════════════════════════════════════

class Role(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("company_id", "role_name"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    role_name: Mapped[str] = mapped_column(String(60), nullable=False)
    role_level: Mapped[int] = mapped_column(SmallInteger, default=5)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False)

    company: Mapped["Company"] = relationship("Company", back_populates="roles")
    users: Mapped[list["User"]] = relationship("User", back_populates="role")
    permissions: Mapped[list["Permission"]] = relationship(
        "Permission", secondary="role_permissions", back_populates="roles"
    )


class Permission(Base, UUIDMixin):
    __tablename__ = "permissions"

    perm_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    module: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    roles: Mapped[list["Role"]] = relationship(
        "Role", secondary="role_permissions", back_populates="permissions"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    perm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("company_id", "email"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret: Mapped[Optional[str]] = mapped_column(Text)
    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[Optional[str]] = mapped_column(INET)
    failed_logins: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)

    company: Mapped["Company"] = relationship("Company", back_populates="users")
    branch: Mapped[Optional["Branch"]] = relationship("Branch", back_populates="users")
    role: Mapped["Role"] = relationship("Role", back_populates="users")
    sessions: Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user")


class UserSession(Base, UUIDMixin):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    device_info: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="sessions")


# ═══════════════════════════════════════════════════════════════════
# SECTION 3: PARTIES (CUSTOMERS & VENDORS)
# ═══════════════════════════════════════════════════════════════════

class Party(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "parties"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    party_type: Mapped[str] = mapped_column(String(10), nullable=False)  # customer|vendor|both
    party_code: Mapped[Optional[str]] = mapped_column(String(30))
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[Optional[str]] = mapped_column(String(200))
    gstin: Mapped[Optional[str]] = mapped_column(String(15))
    pan: Mapped[Optional[str]] = mapped_column(String(10))
    party_category: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(150))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    alt_phone: Mapped[Optional[str]] = mapped_column(String(20))
    billing_address: Mapped[Optional[str]] = mapped_column(Text)
    billing_city: Mapped[Optional[str]] = mapped_column(String(80))
    billing_state: Mapped[Optional[str]] = mapped_column(String(80))
    billing_state_code: Mapped[Optional[str]] = mapped_column(String(30))
    billing_pincode: Mapped[Optional[str]] = mapped_column(String(10))
    shipping_address: Mapped[Optional[str]] = mapped_column(Text)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    credit_days: Mapped[int] = mapped_column(SmallInteger, default=0)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    balance_type: Mapped[str] = mapped_column(String(2), default="Dr")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    tds_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    tds_section: Mapped[Optional[str]] = mapped_column(String(10))   # e.g. 194Q, 194C, 194J
    tds_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))  # percentage, e.g. 0.10
    ai_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    contacts: Mapped[list["PartyContact"]] = relationship("PartyContact", back_populates="party", cascade="all, delete-orphan")


class PartyContact(Base, UUIDMixin):
    __tablename__ = "party_contacts"

    party_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id", ondelete="CASCADE"), nullable=False)
    contact_name: Mapped[Optional[str]] = mapped_column(String(120))
    designation: Mapped[Optional[str]] = mapped_column(String(80))
    email: Mapped[Optional[str]] = mapped_column(String(150))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    party: Mapped["Party"] = relationship("Party", back_populates="contacts")


# ═══════════════════════════════════════════════════════════════════
# SECTION 4: PRODUCTS & INVENTORY
# ═══════════════════════════════════════════════════════════════════

class ProductCategory(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "product_categories"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    cat_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_cat_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("product_categories.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(Text)

    parent: Mapped[Optional["ProductCategory"]] = relationship("ProductCategory", remote_side="ProductCategory.id")
    products: Mapped[list["Product"]] = relationship("Product", back_populates="category")


class UnitOfMeasure(Base, UUIDMixin, SoftDeleteMixin):
    __tablename__ = "units_of_measure"

    uom_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    uom_name: Mapped[str] = mapped_column(String(40), nullable=False)
    base_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("units_of_measure.id"))
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(15, 6), default=Decimal("1"))


class GSTRate(Base, UUIDMixin, SoftDeleteMixin):
    __tablename__ = "gst_rates"

    rate_name: Mapped[str] = mapped_column(String(30), nullable=False)
    total_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, unique=True)
    cgst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    sgst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    igst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    applicable_from: Mapped[Optional[date]] = mapped_column(Date)
    applicable_to: Mapped[Optional[date]] = mapped_column(Date)


class HSNCode(Base, UUIDMixin):
    __tablename__ = "hsn_master"

    hsn_code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    hsn_description: Mapped[Optional[str]] = mapped_column(Text)
    chapter: Mapped[Optional[str]] = mapped_column(String(2))
    heading: Mapped[Optional[str]] = mapped_column(String(4))
    sub_heading: Mapped[Optional[str]] = mapped_column(String(6))
    tariff_item: Mapped[Optional[str]] = mapped_column(String(8))
    gst_rate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("gst_rates.id"))
    is_service: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_from: Mapped[Optional[date]] = mapped_column(Date)

    gst_rate: Mapped[Optional["GSTRate"]] = relationship("GSTRate")


class Product(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "product_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    cat_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("product_categories.id"))
    product_code: Mapped[str] = mapped_column(String(40), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    brand: Mapped[Optional[str]] = mapped_column(String(80))
    model_no: Mapped[Optional[str]] = mapped_column(String(80))
    barcode: Mapped[Optional[str]] = mapped_column(String(50))
    hsn_code: Mapped[Optional[str]] = mapped_column(String(8))
    sac_code: Mapped[Optional[str]] = mapped_column(String(6))
    uom_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("units_of_measure.id"))
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    mrp: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    selling_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    min_selling_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("18"))
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    is_service: Mapped[bool] = mapped_column(Boolean, default=False)
    track_inventory: Mapped[bool] = mapped_column(Boolean, default=True)
    batch_tracking: Mapped[bool] = mapped_column(Boolean, default=False)
    serial_tracking: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry_tracking: Mapped[bool] = mapped_column(Boolean, default=False)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    current_stock: Mapped[int] = mapped_column(Integer, default=0)
    reorder_qty: Mapped[int] = mapped_column(Integer, default=0)
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    images: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    ai_demand_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    category: Mapped[Optional["ProductCategory"]] = relationship("ProductCategory", back_populates="products")
    uom: Mapped[Optional["UnitOfMeasure"]] = relationship("UnitOfMeasure", foreign_keys=[uom_id])
    variants: Mapped[list["ProductVariant"]] = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")


# ═══════════════════════════════════════════════════════════════════
# SECTION 5: AUDIT LOG
# ═══════════════════════════════════════════════════════════════════

class AuditLog(Base, UUIDMixin):
    __tablename__ = "audit_log"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    module: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    entity_ref: Mapped[Optional[str]] = mapped_column(String(50))
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB)
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB)
    changed_fields: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    device_id: Mapped[Optional[str]] = mapped_column(String(100))
    log_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))


# ═══════════════════════════════════════════════════════════════════
# SECTION 6: PRODUCT VARIANTS
# ═══════════════════════════════════════════════════════════════════

class ProductVariant(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """
    Product variants — e.g. Size=L, Colour=Red for a base product.
    Each variant can override SKU, barcode, price, and stock.
    """
    __tablename__ = "product_variants"
    __table_args__ = (UniqueConstraint("product_id", "variant_code"),)

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_code: Mapped[str] = mapped_column(String(40), nullable=False)   # e.g. "RED-L"
    variant_name: Mapped[str] = mapped_column(String(200), nullable=False)  # e.g. "Red / Large"
    # Attribute key-value pairs: {"size": "L", "colour": "Red"}
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    barcode: Mapped[Optional[str]] = mapped_column(String(50))
    mrp: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    selling_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    purchase_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))

    product: Mapped["Product"] = relationship("Product", back_populates="variants")
    # ── Ensure billing, accounting, and inventory models are always registered ──
# These live in separate files; importing them here (not just in Alembic's
# env.py) guarantees their tables are in Base.metadata whenever the app
# runs, so foreign keys referencing them (e.g. Invoice.warehouse_id) resolve
# correctly at runtime, not just during migrations.
from app.db.models.billing import (  # noqa: F401, E402
    Quotation, QuotationItem, JobOrder, JobOrderItem,
    PurchaseOrder, PurchaseOrderItem, GoodsReceiptNote, GRNItem,
    DeliveryChallan, DeliveryChallanItem, Invoice, InvoiceItem,
    Payment, PaymentAllocation, DocumentSequence, EInvoiceLog,
)
from app.db.models.accounting import (  # noqa: F401, E402
    AccountGroup, Account, CostCenter, JournalVoucher, JournalEntry,
    AccountLedger, BankReconciliation, GSTReturn, ITCLedger, FinancialYear,
)
from app.db.models.inventory import (  # noqa: F401, E402
    Warehouse, WarehouseZone, InventoryStock, StockMovement,
    StockAdjustment, StockAdjustmentItem, StockTransfer, StockTransferItem,
    ProductBatch, SerialNumber, BarcodeLabel,
)
from app.db.models.crm import Lead  # noqa: F401, E402