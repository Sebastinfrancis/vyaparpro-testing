"""
VyaparPro — Accounting ORM Models
Chart of Accounts · Account Groups · Journal Vouchers · Journal Entries ·
Account Ledger · Cost Centers · Bank Reconciliation · GST Returns · ITC Ledger
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func,
)
from app.db.types import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models import UUIDMixin, TimestampMixin, SoftDeleteMixin


# ════════════════════════════════════════════════════════════════════
# ACCOUNT GROUPS  (hierarchical — supports unlimited nesting)
# ════════════════════════════════════════════════════════════════════

class AccountGroup(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """
    Hierarchical grouping of accounts:
      Assets → Current Assets → Bank Accounts
      Liabilities → Current Liabilities → GST Payable
    """
    __tablename__ = "account_groups"
    __table_args__ = (UniqueConstraint("company_id", "group_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    group_code: Mapped[str] = mapped_column(String(20), nullable=False)
    group_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_groups.id")
    )
    nature: Mapped[str] = mapped_column(String(12), nullable=False)
    # asset | liability | income | expense | equity
    affects_gross_profit: Mapped[bool] = mapped_column(Boolean, default=False)
    # True = trading account; False = P&L
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # cannot delete

    parent: Mapped[Optional["AccountGroup"]] = relationship(
        "AccountGroup", remote_side="AccountGroup.id", foreign_keys=[parent_group_id]
    )
    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="group")
    children: Mapped[list["AccountGroup"]] = relationship(
        "AccountGroup", foreign_keys=[parent_group_id], back_populates="parent"
    )


# ════════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS
# ════════════════════════════════════════════════════════════════════

class Account(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """
    Every leaf node in the chart of accounts.
    System accounts (cash, bank, GST, etc.) are seeded and protected.
    """
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("company_id", "account_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_groups.id"), nullable=False
    )
    # Gap #4 — optional branch scoping. NULL = company-wide account (old
    # behaviour, still the default for cash/expense/etc). A "bank" account
    # with branch_id set is that branch's own settlement account so
    # multi-branch/multi-GSTIN businesses can settle invoices per branch.
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # cash | bank | receivable | payable | income | expense |
    # fixed_asset | current_asset | current_liability |
    # long_term_liability | equity | stock |
    # gst_input | gst_output | tds_payable | tds_receivable
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    opening_balance_type: Mapped[str] = mapped_column(String(2), default="Dr")
    # Dr | Cr
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    # Bank fields
    bank_name: Mapped[Optional[str]] = mapped_column(String(100))
    bank_account_no: Mapped[Optional[str]] = mapped_column(String(30))
    bank_ifsc: Mapped[Optional[str]] = mapped_column(String(20))
    bank_branch: Mapped[Optional[str]] = mapped_column(String(100))
    bank_account_type: Mapped[Optional[str]] = mapped_column(String(20))  # savings|current|od|cc
    # Flags
    is_reconcilable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_manual_entry: Mapped[bool] = mapped_column(Boolean, default=True)
    # Party link (for sundry debtors / creditors sub-ledgers)
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parties.id")
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    group: Mapped["AccountGroup"] = relationship("AccountGroup", back_populates="accounts")
    ledger_entries: Mapped[list["AccountLedger"]] = relationship(
        "AccountLedger", back_populates="account"
    )


# ════════════════════════════════════════════════════════════════════
# COST CENTERS
# ════════════════════════════════════════════════════════════════════

class CostCenter(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("company_id", "cc_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    cc_code: Mapped[str] = mapped_column(String(20), nullable=False)
    cc_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_cc_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_centers.id")
    )
    budget_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    description: Mapped[Optional[str]] = mapped_column(Text)

    parent: Mapped[Optional["CostCenter"]] = relationship(
        "CostCenter", remote_side="CostCenter.id"
    )


# ════════════════════════════════════════════════════════════════════
# JOURNAL VOUCHERS
# ════════════════════════════════════════════════════════════════════

class JournalVoucher(Base, UUIDMixin, TimestampMixin):
    """
    Header record for every accounting transaction.
    Types: payment | receipt | contra | journal | purchase | sale |
           debit_note | credit_note | opening | closing | depreciation
    Each JV must balance: sum(debit) == sum(credit).
    """
    __tablename__ = "journal_vouchers"
    __table_args__ = (UniqueConstraint("company_id", "jv_no"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id")
    )
    jv_no: Mapped[str] = mapped_column(String(30), nullable=False)
    jv_type: Mapped[str] = mapped_column(String(20), nullable=False)
    jv_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    narration: Mapped[Optional[str]] = mapped_column(Text)
    # Source document link
    ref_type: Mapped[Optional[str]] = mapped_column(String(30))
    # invoice | purchase_bill | payment | jo | po | adjustment
    ref_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    ref_no: Mapped[Optional[str]] = mapped_column(String(30))
    # Totals (denormalized for fast reporting)
    total_debit: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_credit: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    # Workflow
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    reversed_jv_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_vouchers.id"))
    financial_year: Mapped[Optional[str]] = mapped_column(String(7))  # '2025-26'
    period: Mapped[Optional[str]] = mapped_column(String(7))          # '2025-06'
    cost_center_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("cost_centers.id"))
    tags: Mapped[Optional[list[str]]] = mapped_column(JSONB)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    entries: Mapped[list["JournalEntry"]] = relationship(
        "JournalEntry", back_populates="voucher", cascade="all, delete-orphan"
    )
    reversed_jv: Mapped[Optional["JournalVoucher"]] = relationship(
        "JournalVoucher", remote_side="JournalVoucher.id", foreign_keys=[reversed_jv_id]
    )


class JournalEntry(Base, UUIDMixin):
    """Single debit or credit line within a JournalVoucher."""
    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint(
            "NOT (debit_amount > 0 AND credit_amount > 0)",
            name="chk_one_side_only"
        ),
        CheckConstraint("debit_amount >= 0 AND credit_amount >= 0", name="chk_non_negative"),
    )

    jv_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_vouchers.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    narration: Mapped[Optional[str]] = mapped_column(Text)
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    cost_center_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("cost_centers.id"))
    reconciled: Mapped[bool] = mapped_column(Boolean, default=False)
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    voucher: Mapped["JournalVoucher"] = relationship("JournalVoucher", back_populates="entries")
    account: Mapped["Account"] = relationship("Account")


# ════════════════════════════════════════════════════════════════════
# ACCOUNT LEDGER  (running balance per account)
# ════════════════════════════════════════════════════════════════════

class AccountLedger(Base, UUIDMixin):
    """
    Materialized ledger — one row per JournalEntry, carrying running balance.
    Rebuilt from JournalEntries; used for fast ledger, cash book, bank book.
    """
    __tablename__ = "account_ledger"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    jv_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_vouchers.id"), nullable=False
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"), nullable=False
    )
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    jv_no: Mapped[str] = mapped_column(String(30), nullable=False)
    jv_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ref_type: Mapped[Optional[str]] = mapped_column(String(30))
    ref_no: Mapped[Optional[str]] = mapped_column(String(30))
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    running_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    balance_type: Mapped[str] = mapped_column(String(2), default="Dr")  # Dr | Cr
    narration: Mapped[Optional[str]] = mapped_column(Text)
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    cost_center_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("cost_centers.id"))
    financial_year: Mapped[Optional[str]] = mapped_column(String(7))
    period: Mapped[Optional[str]] = mapped_column(String(7))

    account: Mapped["Account"] = relationship("Account", back_populates="ledger_entries")
    voucher: Mapped["JournalVoucher"] = relationship("JournalVoucher")


# ════════════════════════════════════════════════════════════════════
# BANK RECONCILIATION
# ════════════════════════════════════════════════════════════════════

class BankReconciliation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "bank_reconciliations"
    __table_args__ = (UniqueConstraint("company_id", "account_id", "statement_date"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    statement_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    book_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    difference: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    uncleared_debits: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    uncleared_credits: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|reconciled
    notes: Mapped[Optional[str]] = mapped_column(Text)
    reconciled_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


# ════════════════════════════════════════════════════════════════════
# GST RETURNS
# ════════════════════════════════════════════════════════════════════

class GSTReturn(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "gst_returns"
    __table_args__ = (UniqueConstraint("company_id", "return_type", "period_from"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True)
    return_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # GSTR-1 | GSTR-2A | GSTR-2B | GSTR-3B | GSTR-9 | GSTR-9C
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    financial_year: Mapped[Optional[str]] = mapped_column(String(7))
    # Turnover
    taxable_turnover: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    exempt_turnover: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    nil_turnover: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    # Output GST
    total_cgst_output: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_sgst_output: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_igst_output: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_cess_output: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    # Input Tax Credit
    itc_cgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    itc_sgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    itc_igst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    itc_cess: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    # Net payable
    net_cgst_payable: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    net_sgst_payable: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    net_igst_payable: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_tax_payable: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    # Filing
    filed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    filed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    arn: Mapped[Optional[str]] = mapped_column(String(30))  # Acknowledgement Reference Number
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft | prepared | filed | revised | nil
    json_data: Mapped[Optional[dict]] = mapped_column(JSONB)  # full JSON for NIC portal


# ════════════════════════════════════════════════════════════════════
# ITC LEDGER  (Input Tax Credit monthly balance)
# ════════════════════════════════════════════════════════════════════

class ITCLedger(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "itc_ledger"
    __table_args__ = (UniqueConstraint("company_id", "period"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)   # first day of month
    # Opening
    opening_cgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    opening_sgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    opening_igst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    opening_cess: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    # Credits claimed
    credit_cgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    credit_sgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    credit_igst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    credit_cess: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    # Utilized against liability
    utilized_cgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    utilized_sgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    utilized_igst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    utilized_cess: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    # Closing
    closing_cgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    closing_sgst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    closing_igst: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    closing_cess: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))


# ════════════════════════════════════════════════════════════════════
# FINANCIAL YEAR CONFIG
# ════════════════════════════════════════════════════════════════════

class FinancialYear(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "financial_years"
    __table_args__ = (UniqueConstraint("company_id", "fy_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    fy_code: Mapped[str] = mapped_column(String(7), nullable=False)  # '2025-26'
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # no posting after lock
    closing_entry_jv_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_vouchers.id"))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
