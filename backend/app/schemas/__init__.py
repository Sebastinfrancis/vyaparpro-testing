"""
VyaparPro — Pydantic v2 Schemas
Request/response models for all API endpoints.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import (
    BaseModel, ConfigDict, EmailStr, Field, field_validator,
    model_validator,
)

# ── Shared config ─────────────────────────────────────────────────────────────

class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )


# ── API envelope ─────────────────────────────────────────────────────────────

class APIResponse(APIModel):
    success: bool = True
    message: str = "OK"
    data: Any = None


class PaginatedResponse(APIModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


class ErrorResponse(APIModel):
    success: bool = False
    error_code: str
    message: str
    detail: Any = None


# ── Validators ────────────────────────────────────────────────────────────────

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
PAN_RE   = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")


def validate_gstin(v: str | None) -> str | None:
    if v and not GSTIN_RE.match(v.upper()):
        raise ValueError("Invalid GSTIN format (e.g. 27AABCS1234F1Z5)")
    return v.upper() if v else v


def validate_pan(v: str | None) -> str | None:
    if v and not PAN_RE.match(v.upper()):
        raise ValueError("Invalid PAN format (e.g. AABCS1234F)")
    return v.upper() if v else v


# ════════════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════════════

class LoginRequest(APIModel):
    email: EmailStr
    password: str
    company_id: UUID
    totp_code: Optional[str] = None
    device_info: Optional[dict] = None


class TokenResponse(APIModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


class RefreshRequest(APIModel):
    refresh_token: str


class ChangePasswordRequest(APIModel):
    current_password: str
    new_password: str = Field(min_length=8)
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class ForgotPasswordRequest(APIModel):
    email: EmailStr
    company_id: UUID


class ResetPasswordRequest(APIModel):
    token: str
    new_password: str = Field(min_length=8)
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self) -> "ResetPasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class Setup2FAResponse(APIModel):
    secret: str
    qr_uri: str


class Verify2FARequest(APIModel):
    totp_code: str


# ════════════════════════════════════════════════════════════════════
# ORGANIZATION
# ════════════════════════════════════════════════════════════════════

class OrganizationCreate(APIModel):
    org_name: str = Field(max_length=200)
    org_type: str = "company"
    parent_org_id: Optional[UUID] = None


class OrganizationOut(APIModel):
    id: UUID
    org_name: str
    org_type: str
    parent_org_id: Optional[UUID]
    is_active: bool
    created_at: datetime


# ════════════════════════════════════════════════════════════════════
# COMPANY
# ════════════════════════════════════════════════════════════════════

class CompanyCreate(APIModel):
    org_id: UUID
    legal_name: str = Field(max_length=200)
    trade_name: Optional[str] = Field(None, max_length=200)
    gstin: Optional[str] = Field(None, max_length=15)
    pan: Optional[str] = Field(None, max_length=10)
    tan: Optional[str] = Field(None, max_length=10)
    cin: Optional[str] = Field(None, max_length=21)
    business_type: str = "retailer"
    reg_address: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    website: Optional[str] = None
    financial_year_start: int = Field(default=4, ge=1, le=12)
    currency: str = Field(default="INR", max_length=3)
    country: str = Field(default="IN", max_length=2)
    state_code: Optional[str] = Field(None, max_length=2)
    invoice_prefix: str = "INV-"
    po_prefix: str = "PO-"
    jo_prefix: str = "JO-"
    quote_prefix: str = "QT-"

    @field_validator("gstin")
    @classmethod
    def check_gstin(cls, v: str | None) -> str | None:
        return validate_gstin(v)

    @field_validator("pan")
    @classmethod
    def check_pan(cls, v: str | None) -> str | None:
        return validate_pan(v)


class CompanyUpdate(APIModel):
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    reg_address: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    invoice_prefix: Optional[str] = None
    po_prefix: Optional[str] = None
    jo_prefix: Optional[str] = None
    settings: Optional[dict] = None


class CompanyOut(APIModel):
    id: UUID
    org_id: UUID
    legal_name: str
    trade_name: Optional[str]
    gstin: Optional[str]
    pan: Optional[str]
    business_type: str
    reg_address: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    website: Optional[str]
    logo_url: Optional[str]
    financial_year_start: int
    currency: str
    country: str
    state_code: Optional[str]
    invoice_prefix: str
    po_prefix: str
    jo_prefix: str
    quote_prefix: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ════════════════════════════════════════════════════════════════════
# BRANCH
# ════════════════════════════════════════════════════════════════════

class BranchCreate(APIModel):
    branch_code: str = Field(max_length=20)
    branch_name: str = Field(max_length=150)
    gstin: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=80)
    state: Optional[str] = Field(None, max_length=80)
    state_code: Optional[str] = Field(None, max_length=2)
    pincode: Optional[str] = Field(None, max_length=10)
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    branch_type: str = "branch"

    @field_validator("gstin")
    @classmethod
    def check_gstin(cls, v: str | None) -> str | None:
        return validate_gstin(v)


class BranchUpdate(APIModel):
    branch_name: Optional[str] = None
    gstin: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    branch_type: Optional[str] = None
    is_active: Optional[bool] = None


class BranchOut(APIModel):
    id: UUID
    company_id: UUID
    branch_code: str
    branch_name: str
    gstin: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    state_code: Optional[str]
    pincode: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    branch_type: str
    is_active: bool
    created_at: datetime


# ════════════════════════════════════════════════════════════════════
# ROLES & PERMISSIONS
# ════════════════════════════════════════════════════════════════════

class PermissionOut(APIModel):
    id: UUID
    perm_code: str
    module: str
    action: str
    description: Optional[str]


class RoleCreate(APIModel):
    role_name: str = Field(max_length=60)
    role_level: int = Field(default=5, ge=1, le=10)
    description: Optional[str] = None
    permission_ids: list[UUID] = Field(default_factory=list)


class RoleUpdate(APIModel):
    role_name: Optional[str] = None
    role_level: Optional[int] = Field(None, ge=1, le=10)
    description: Optional[str] = None
    permission_ids: Optional[list[UUID]] = None


class RoleOut(APIModel):
    id: UUID
    company_id: UUID
    role_name: str
    role_level: int
    description: Optional[str]
    is_system_role: bool
    permissions: list[PermissionOut] = []
    created_at: datetime


# ════════════════════════════════════════════════════════════════════
# USER
# ════════════════════════════════════════════════════════════════════

class UserCreate(APIModel):
    full_name: str = Field(max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=20)
    password: str = Field(min_length=8)
    role_id: UUID
    branch_id: Optional[UUID] = None


class UserUpdate(APIModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role_id: Optional[UUID] = None
    branch_id: Optional[UUID] = None
    is_active: Optional[bool] = None
    avatar_url: Optional[str] = None
    preferences: Optional[dict] = None


class UserOut(APIModel):
    id: UUID
    company_id: UUID
    full_name: str
    email: str
    phone: Optional[str]
    role_id: UUID
    branch_id: Optional[UUID]
    is_2fa_enabled: bool
    is_active: bool
    avatar_url: Optional[str]
    last_login_at: Optional[datetime]
    created_at: datetime
    role: Optional[RoleOut] = None


# ════════════════════════════════════════════════════════════════════
# PARTY (CUSTOMER / VENDOR)
# ════════════════════════════════════════════════════════════════════

class PartyContactCreate(APIModel):
    contact_name: Optional[str] = None
    designation: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    is_primary: bool = False


class PartyContactOut(APIModel):
    id: UUID
    contact_name: Optional[str]
    designation: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    is_primary: bool


class PartyCreate(APIModel):
    party_type: str = Field(pattern=r"^(customer|vendor|both)$")
    display_name: str = Field(max_length=200)
    legal_name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    party_category: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    alt_phone: Optional[str] = None
    billing_address: Optional[str] = None
    billing_city: Optional[str] = None
    billing_state: Optional[str] = None
    billing_state_code: Optional[str] = Field(None, max_length=2)
    billing_pincode: Optional[str] = None
    shipping_address: Optional[str] = None
    credit_limit: Decimal = Decimal("0")
    credit_days: int = 0
    opening_balance: Decimal = Decimal("0")
    balance_type: str = "Dr"
    currency: str = "INR"
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    contacts: list[PartyContactCreate] = Field(default_factory=list)

    @field_validator("gstin")
    @classmethod
    def check_gstin(cls, v: str | None) -> str | None:
        return validate_gstin(v)

    @field_validator("pan")
    @classmethod
    def check_pan(cls, v: str | None) -> str | None:
        return validate_pan(v)


class PartyUpdate(APIModel):
    display_name: Optional[str] = None
    legal_name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    party_category: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    alt_phone: Optional[str] = None
    billing_address: Optional[str] = None
    billing_city: Optional[str] = None
    billing_state: Optional[str] = None
    billing_pincode: Optional[str] = None
    shipping_address: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    credit_days: Optional[int] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    is_active: Optional[bool] = None


class PartyOut(APIModel):
    id: UUID
    company_id: UUID
    party_type: str
    party_code: Optional[str]
    display_name: str
    legal_name: Optional[str]
    gstin: Optional[str]
    pan: Optional[str]
    party_category: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    alt_phone: Optional[str]
    billing_address: Optional[str]
    billing_city: Optional[str]
    billing_state: Optional[str]
    billing_state_code: Optional[str]
    billing_pincode: Optional[str]
    credit_limit: Decimal
    credit_days: int
    opening_balance: Decimal
    balance_type: str
    currency: str
    ai_score: Optional[Decimal]
    tags: Optional[list[str]]
    notes: Optional[str]
    is_active: bool
    created_at: datetime
    contacts: list[PartyContactOut] = []


# ════════════════════════════════════════════════════════════════════
# PRODUCT CATEGORY
# ════════════════════════════════════════════════════════════════════

class CategoryCreate(APIModel):
    cat_name: str = Field(max_length=100)
    parent_cat_id: Optional[UUID] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class CategoryUpdate(APIModel):
    cat_name: Optional[str] = None
    parent_cat_id: Optional[UUID] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


class CategoryOut(APIModel):
    id: UUID
    company_id: UUID
    cat_name: str
    parent_cat_id: Optional[UUID]
    description: Optional[str]
    image_url: Optional[str]
    is_active: bool
    created_at: datetime


# ════════════════════════════════════════════════════════════════════
# UNIT OF MEASURE
# ════════════════════════════════════════════════════════════════════

class UOMCreate(APIModel):
    uom_code: str = Field(max_length=10)
    uom_name: str = Field(max_length=40)
    base_unit_id: Optional[UUID] = None
    conversion_factor: Decimal = Decimal("1")


class UOMOut(APIModel):
    id: UUID
    uom_code: str
    uom_name: str
    base_unit_id: Optional[UUID]
    conversion_factor: Decimal
    is_active: bool


# ════════════════════════════════════════════════════════════════════
# GST RATES
# ════════════════════════════════════════════════════════════════════

class GSTRateOut(APIModel):
    id: UUID
    rate_name: str
    total_rate: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cess_rate: Decimal
    is_active: bool


# ════════════════════════════════════════════════════════════════════
# HSN CODES
# ════════════════════════════════════════════════════════════════════

class HSNCodeOut(APIModel):
    id: UUID
    hsn_code: str
    hsn_description: Optional[str]
    chapter: Optional[str]
    is_service: bool
    gst_rate: Optional[GSTRateOut]


# ════════════════════════════════════════════════════════════════════
# PRODUCT
# ════════════════════════════════════════════════════════════════════

class ProductCreate(APIModel):
    product_code: str = Field(max_length=40)
    product_name: str = Field(max_length=200)
    description: Optional[str] = None
    cat_id: Optional[UUID] = None
    brand: Optional[str] = None
    model_no: Optional[str] = None
    barcode: Optional[str] = None
    hsn_code: Optional[str] = Field(None, max_length=8)
    sac_code: Optional[str] = Field(None, max_length=6)
    uom_id: Optional[UUID] = None
    purchase_price: Decimal = Field(default=Decimal("0"), ge=0)
    mrp: Decimal = Field(default=Decimal("0"), ge=0)
    selling_price: Decimal = Field(default=Decimal("0"), ge=0)
    min_selling_price: Decimal = Field(default=Decimal("0"), ge=0)
    gst_rate: Decimal = Field(default=Decimal("18"), ge=0)
    cess_rate: Decimal = Field(default=Decimal("0"), ge=0)
    is_service: bool = False
    track_inventory: bool = True
    batch_tracking: bool = False
    serial_tracking: bool = False
    expiry_tracking: bool = False
    current_stock: int = 0
    reorder_level: Decimal = Decimal("0")
    reorder_qty: Decimal = Decimal("0")
    image_url: Optional[str] = None
    tags: Optional[list[str]] = None


class ProductUpdate(APIModel):
    product_name: Optional[str] = None
    description: Optional[str] = None
    cat_id: Optional[UUID] = None
    brand: Optional[str] = None
    barcode: Optional[str] = None
    hsn_code: Optional[str] = None
    uom_id: Optional[UUID] = None
    purchase_price: Optional[Decimal] = None
    mrp: Optional[Decimal] = None
    selling_price: Optional[Decimal] = None
    min_selling_price: Optional[Decimal] = None
    gst_rate: Optional[Decimal] = None
    current_stock: Optional[int] = None
    reorder_level: Optional[Decimal] = None
    reorder_qty: Optional[Decimal] = None
    image_url: Optional[str] = None
    tags: Optional[list[str]] = None
    is_active: Optional[bool] = None


class ProductOut(APIModel):
    id: UUID
    company_id: UUID
    product_code: str
    product_name: str
    description: Optional[str]
    brand: Optional[str]
    model_no: Optional[str]
    barcode: Optional[str]
    hsn_code: Optional[str]
    sac_code: Optional[str]
    purchase_price: Decimal
    mrp: Decimal
    selling_price: Decimal
    min_selling_price: Decimal
    gst_rate: Decimal
    cess_rate: Decimal
    is_service: bool
    track_inventory: bool
    current_stock: int
    reorder_level: Decimal
    reorder_qty: int
    image_url: Optional[str]
    tags: Optional[list[str]]
    ai_demand_score: Optional[Decimal]
    is_active: bool
    created_at: datetime
    category: Optional[CategoryOut] = None
    uom: Optional[UOMOut] = None


# ════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ════════════════════════════════════════════════════════════════════

class AuditLogOut(APIModel):
    id: UUID
    action: str
    module: str
    entity_type: Optional[str]
    entity_ref: Optional[str]
    changed_fields: Optional[list[str]]
    ip_address: Optional[str]
    log_timestamp: datetime
    user_id: Optional[UUID]


# ════════════════════════════════════════════════════════════════════
# PRODUCT VARIANTS (appended — models added in Section 6)
# ════════════════════════════════════════════════════════════════════

class ProductVariantCreate(APIModel):
    variant_code: str = Field(max_length=40)
    variant_name: str = Field(max_length=200)
    attributes: dict = Field(default_factory=dict)
    barcode: Optional[str] = Field(None, max_length=50)
    mrp: Optional[Decimal] = Field(None, ge=0)
    selling_price: Optional[Decimal] = Field(None, ge=0)
    purchase_price: Optional[Decimal] = Field(None, ge=0)
    image_url: Optional[str] = None
    reorder_level: Decimal = Decimal("0")


class ProductVariantUpdate(APIModel):
    variant_name: Optional[str] = None
    attributes: Optional[dict] = None
    barcode: Optional[str] = None
    mrp: Optional[Decimal] = None
    selling_price: Optional[Decimal] = None
    purchase_price: Optional[Decimal] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


class ProductVariantOut(APIModel):
    id: UUID
    product_id: UUID
    variant_code: str
    variant_name: str
    attributes: dict
    barcode: Optional[str]
    mrp: Optional[Decimal]
    selling_price: Optional[Decimal]
    purchase_price: Optional[Decimal]
    image_url: Optional[str]
    reorder_level: Decimal
    is_active: bool
    created_at: datetime


# ════════════════════════════════════════════════════════════════════
# EXTENDED ProductOut with variants
# ════════════════════════════════════════════════════════════════════

class ProductDetailOut(ProductOut):
    """Full product response including variants list."""
    variants: list[ProductVariantOut] = []

