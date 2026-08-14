"""
VyaparPro — Accounting Pydantic Schemas
Request / response models for every accounting endpoint.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas import APIModel


# ════════════════════════════════════════════════════════════════════
# ACCOUNT GROUPS
# ════════════════════════════════════════════════════════════════════

class AccountGroupCreate(APIModel):
    group_code: str = Field(max_length=20)
    group_name: str = Field(max_length=100)
    nature: str = Field(pattern=r"^(asset|liability|income|expense|equity)$")
    parent_group_id: Optional[UUID] = None
    affects_gross_profit: bool = False
    display_order: int = 0


class AccountGroupUpdate(APIModel):
    group_name: Optional[str] = None
    parent_group_id: Optional[UUID] = None
    affects_gross_profit: Optional[bool] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class AccountGroupOut(APIModel):
    id: UUID
    company_id: UUID
    group_code: str
    group_name: str
    nature: str
    parent_group_id: Optional[UUID]
    affects_gross_profit: bool
    display_order: int
    is_system: bool
    is_active: bool
    created_at: datetime


# ════════════════════════════════════════════════════════════════════
# ACCOUNTS (Chart of Accounts)
# ════════════════════════════════════════════════════════════════════

class AccountCreate(APIModel):
    group_id: UUID
    account_code: str = Field(max_length=20)
    account_name: str = Field(max_length=150)
    account_type: str = Field(max_length=30)
    opening_balance: Decimal = Decimal("0")
    opening_balance_type: str = "Dr"
    currency: str = "INR"
    # Gap #4 — leave unset for a company-wide account; set to scope a bank
    # account (typically) to one branch for per-branch settlement.
    branch_id: Optional[UUID] = None
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_branch: Optional[str] = None
    bank_account_type: Optional[str] = None
    is_reconcilable: bool = False
    allow_manual_entry: bool = True
    party_id: Optional[UUID] = None
    description: Optional[str] = None


class AccountUpdate(APIModel):
    account_name: Optional[str] = None
    group_id: Optional[UUID] = None
    opening_balance: Optional[Decimal] = None
    branch_id: Optional[UUID] = None
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_branch: Optional[str] = None
    is_reconcilable: Optional[bool] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AccountOut(APIModel):
    id: UUID
    company_id: UUID
    group_id: UUID
    account_code: str
    account_name: str
    account_type: str
    opening_balance: Decimal
    opening_balance_type: str
    currency: str
    branch_id: Optional[UUID]
    bank_name: Optional[str]
    bank_account_no: Optional[str]
    bank_ifsc: Optional[str]
    is_reconcilable: bool
    is_system: bool
    is_active: bool
    created_at: datetime
    # Computed
    current_balance: Optional[Decimal] = None
    balance_type: Optional[str] = None
    group: Optional[AccountGroupOut] = None


# ════════════════════════════════════════════════════════════════════
# JOURNAL VOUCHERS
# ════════════════════════════════════════════════════════════════════

class JournalEntryLine(APIModel):
    account_id: UUID
    debit_amount: Decimal = Decimal("0")
    credit_amount: Decimal = Decimal("0")
    narration: Optional[str] = None
    party_id: Optional[UUID] = None
    cost_center_id: Optional[UUID] = None

    @model_validator(mode="after")
    def one_side_only(self) -> "JournalEntryLine":
        if self.debit_amount > 0 and self.credit_amount > 0:
            raise ValueError("A line cannot have both debit and credit amounts.")
        if self.debit_amount == 0 and self.credit_amount == 0:
            raise ValueError("A line must have either a debit or credit amount.")
        return self


class JournalVoucherCreate(APIModel):
    jv_type: str = Field(
        pattern=r"^(payment|receipt|contra|journal|purchase|sale|debit_note|credit_note|opening|closing|depreciation)$"
    )
    jv_date: date
    narration: Optional[str] = None
    ref_type: Optional[str] = None
    ref_id: Optional[UUID] = None
    ref_no: Optional[str] = None
    cost_center_id: Optional[UUID] = None
    entries: list[JournalEntryLine] = Field(min_length=2)

    @model_validator(mode="after")
    def must_balance(self) -> "JournalVoucherCreate":
        total_dr = sum(e.debit_amount for e in self.entries)
        total_cr = sum(e.credit_amount for e in self.entries)
        if abs(total_dr - total_cr) > Decimal("0.01"):
            raise ValueError(f"Voucher is unbalanced: Dr={total_dr} Cr={total_cr}")
        return self


class JournalVoucherUpdate(APIModel):
    jv_date: Optional[date] = None
    narration: Optional[str] = None
    entries: Optional[list[JournalEntryLine]] = None


class JournalEntryOut(APIModel):
    id: UUID
    account_id: UUID
    debit_amount: Decimal
    credit_amount: Decimal
    narration: Optional[str]
    party_id: Optional[UUID]
    cost_center_id: Optional[UUID]
    display_order: int
    account: Optional[AccountOut] = None


class JournalVoucherOut(APIModel):
    id: UUID
    company_id: UUID
    branch_id: Optional[UUID]
    jv_no: str
    jv_type: str
    jv_date: date
    narration: Optional[str]
    ref_type: Optional[str]
    ref_id: Optional[UUID]
    ref_no: Optional[str]
    total_debit: Decimal
    total_credit: Decimal
    is_posted: bool
    is_reversed: bool
    posted_at: Optional[datetime]
    financial_year: Optional[str]
    created_at: datetime
    entries: list[JournalEntryOut] = []


# ════════════════════════════════════════════════════════════════════
# LEDGER
# ════════════════════════════════════════════════════════════════════

class LedgerEntryOut(APIModel):
    id: UUID
    account_id: UUID
    txn_date: date
    jv_no: str
    jv_type: str
    ref_type: Optional[str]
    ref_no: Optional[str]
    narration: Optional[str]
    debit_amount: Decimal
    credit_amount: Decimal
    running_balance: Decimal
    balance_type: str
    party_id: Optional[UUID]


class LedgerOut(APIModel):
    account_id: UUID
    account_code: str
    account_name: str
    opening_balance: Decimal
    opening_balance_type: str
    total_debit: Decimal
    total_credit: Decimal
    closing_balance: Decimal
    closing_balance_type: str
    entries: list[LedgerEntryOut] = []
    total: int = 0
    page: int = 1
    page_size: int = 50
    pages: int = 1


# ════════════════════════════════════════════════════════════════════
# PAYMENT / RECEIPT VOUCHER (convenience wrappers)
# ════════════════════════════════════════════════════════════════════

class PaymentVoucherCreate(APIModel):
    """Simplified form for recording a payment (cash/bank going out)."""
    voucher_date: date
    pay_from_account_id: UUID      # cash or bank account
    pay_to_account_id: UUID        # expense / payable account
    amount: Decimal = Field(gt=0)
    party_id: Optional[UUID] = None
    narration: Optional[str] = None
    ref_no: Optional[str] = None
    payment_method: str = "cash"


class ReceiptVoucherCreate(APIModel):
    """Simplified form for recording a receipt (cash/bank coming in)."""
    voucher_date: date
    receive_in_account_id: UUID    # cash or bank account
    receive_from_account_id: UUID  # receivable / income account
    amount: Decimal = Field(gt=0)
    party_id: Optional[UUID] = None
    narration: Optional[str] = None
    ref_no: Optional[str] = None
    payment_method: str = "cash"


class ContraVoucherCreate(APIModel):
    """Cash ↔ Bank or Bank ↔ Bank transfer."""
    voucher_date: date
    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal = Field(gt=0)
    narration: Optional[str] = None


class CapitalVoucherCreate(APIModel):
    """Owner introduces capital into the business, or withdraws (drawings)."""
    voucher_date: date
    cash_bank_account_id: UUID          # which Cash/Bank account money moves through
    txn_type: str                       # "introduce" | "drawings"
    amount: Decimal = Field(gt=0)
    narration: Optional[str] = None


# ════════════════════════════════════════════════════════════════════
# REPORTS
# ════════════════════════════════════════════════════════════════════

class TrialBalanceRow(APIModel):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    group_name: str
    opening_dr: Decimal = Decimal("0")
    opening_cr: Decimal = Decimal("0")
    period_dr: Decimal = Decimal("0")
    period_cr: Decimal = Decimal("0")
    closing_dr: Decimal = Decimal("0")
    closing_cr: Decimal = Decimal("0")


class TrialBalanceOut(APIModel):
    company_id: UUID
    from_date: date
    to_date: date
    rows: list[TrialBalanceRow]
    total_dr: Decimal
    total_cr: Decimal
    is_balanced: bool


class PLRow(APIModel):
    label: str
    amount: Decimal
    is_heading: bool = False
    children: list["PLRow"] = []


class ProfitLossOut(APIModel):
    company_id: UUID
    from_date: date
    to_date: date
    gross_profit: Decimal
    operating_profit: Decimal
    net_profit: Decimal
    rows: list[PLRow]


class BalanceSheetRow(APIModel):
    label: str
    amount: Decimal
    is_heading: bool = False
    children: list["BalanceSheetRow"] = []


class BalanceSheetOut(APIModel):
    company_id: UUID
    as_of_date: date
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    assets: list[BalanceSheetRow]
    liabilities: list[BalanceSheetRow]


# ════════════════════════════════════════════════════════════════════
# GST REPORTS
# ════════════════════════════════════════════════════════════════════

class GSTReportFilter(APIModel):
    from_date: date
    to_date: date
    return_type: Optional[str] = None


class GSTSummaryRow(APIModel):
    period: str
    taxable_amount: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    total_gst: Decimal
    total_value: Decimal
    invoice_count: int


class GSTR1Row(APIModel):
    invoice_no: str
    invoice_date: date
    party_name: str
    party_gstin: Optional[str]
    place_of_supply: str
    supply_type: str
    taxable_amount: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    total_amount: Decimal
    invoice_type: str


class GSTR3BRow(APIModel):
    description: str
    taxable_amount: Decimal
    integrated_tax: Decimal
    central_tax: Decimal
    state_tax: Decimal
    cess: Decimal


class GSTReturnOut(APIModel):
    id: UUID
    company_id: UUID
    return_type: str
    period_from: date
    period_to: date
    financial_year: Optional[str]
    taxable_turnover: Decimal
    total_cgst_output: Decimal
    total_sgst_output: Decimal
    total_igst_output: Decimal
    itc_cgst: Decimal
    itc_sgst: Decimal
    itc_igst: Decimal
    net_cgst_payable: Decimal
    net_sgst_payable: Decimal
    net_igst_payable: Decimal
    total_tax_payable: Decimal
    arn: Optional[str]
    status: str
    filed_at: Optional[datetime]
    created_at: datetime


# ════════════════════════════════════════════════════════════════════
# FINANCIAL YEAR
# ════════════════════════════════════════════════════════════════════

class FinancialYearCreate(APIModel):
    fy_code: str = Field(pattern=r"^\d{4}-\d{2}$")
    start_date: date
    end_date: date


class FinancialYearOut(APIModel):
    id: UUID
    company_id: UUID
    fy_code: str
    start_date: date
    end_date: date
    is_current: bool
    is_locked: bool
    created_at: datetime


# ════════════════════════════════════════════════════════════════════
# COST CENTERS
# ════════════════════════════════════════════════════════════════════

class CostCenterCreate(APIModel):
    cc_code: str = Field(max_length=20)
    cc_name: str = Field(max_length=100)
    parent_cc_id: Optional[UUID] = None
    budget_amount: Optional[Decimal] = None
    description: Optional[str] = None


class CostCenterOut(APIModel):
    id: UUID
    company_id: UUID
    cc_code: str
    cc_name: str
    parent_cc_id: Optional[UUID]
    budget_amount: Optional[Decimal]
    is_active: bool
    created_at: datetime
