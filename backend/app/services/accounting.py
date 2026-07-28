"""
VyaparPro — Accounting Service Layer
Business logic for every accounting operation:
  - Chart of accounts management
  - Journal voucher creation and posting
  - Automated double-entry from billing events
  - Trial Balance, P&L, Balance Sheet computation
  - GST return computation (GSTR-1, GSTR-3B)
  - Cash book, Bank book, Ledger
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError, BusinessError, NotFoundError, PermissionDeniedError,
)
from app.db.models.accounting import (
    Account, AccountGroup, AccountLedger, FinancialYear,
    JournalEntry, JournalVoucher,
)
from app.db.repositories.accounting import (
    AccountGroupRepository, AccountLedgerRepository, AccountRepository,
    CostCenterRepository, FinancialYearRepository, GSTReturnRepository,
    ITCLedgerRepository, JournalVoucherRepository,
)
from app.schemas.accounting import (
    AccountCreate, AccountGroupCreate, AccountUpdate,
    ContraVoucherCreate, FinancialYearCreate,
    JournalVoucherCreate, LedgerEntryOut, LedgerOut, PaymentVoucherCreate,
    ReceiptVoucherCreate, TrialBalanceOut, TrialBalanceRow,
    ProfitLossOut, PLRow, BalanceSheetOut, BalanceSheetRow,
    GSTReturnOut, GSTR1Row, GSTR3BRow,
)
from app.utils.gst_calculator import GSTCalculator


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _fy_code(d: date) -> str:
    """Return financial year code for a date, e.g. '2025-26'."""
    if d.month >= 4:
        return f"{d.year}-{str(d.year + 1)[2:]}"
    return f"{d.year - 1}-{str(d.year)[2:]}"


def _period_code(d: date) -> str:
    return d.strftime("%Y-%m")


# ═══════════════════════════════════════════════════════════════════
# ACCOUNT GROUP SERVICE
# ═══════════════════════════════════════════════════════════════════

class AccountGroupService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AccountGroupRepository(session)

    async def create(self, company_id: UUID, payload: AccountGroupCreate, user_id: UUID) -> AccountGroup:
        existing = await self.repo.get_by(company_id=company_id, group_code=payload.group_code)
        if existing:
            raise AlreadyExistsError(f"Account group code '{payload.group_code}' already exists.")
        data = payload.model_dump()
        data["company_id"] = company_id
        return await self.repo.create(data)

    async def get_tree(self, company_id: UUID) -> list[AccountGroup]:
        return await self.repo.get_tree(company_id)

    async def update(self, group_id: UUID, payload: Any, company_id: UUID) -> AccountGroup:
        group = await self.repo.get_or_raise(group_id)
        if group.is_system:
            raise PermissionDeniedError("System account groups cannot be modified.")
        return await self.repo.update(group, payload.model_dump(exclude_unset=True))


# ═══════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS SERVICE
# ═══════════════════════════════════════════════════════════════════

class ChartOfAccountsService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AccountRepository(session)
        self.group_repo = AccountGroupRepository(session)

    async def create(self, company_id: UUID, payload: AccountCreate, user_id: UUID) -> Account:
        existing = await self.repo.get_by(company_id=company_id, account_code=payload.account_code)
        if existing:
            raise AlreadyExistsError(f"Account code '{payload.account_code}' already exists.")
        group = await self.group_repo.get_or_raise(payload.group_id)
        if group.company_id != company_id:
            raise PermissionDeniedError("Account group belongs to a different company.")
        data = payload.model_dump()
        data.update({"company_id": company_id, "created_by": user_id})
        return await self.repo.create(data)

    async def update(self, account_id: UUID, payload: AccountUpdate, company_id: UUID) -> Account:
        account = await self.repo.get_or_raise(account_id)
        if account.company_id != company_id:
            raise PermissionDeniedError()
        if account.is_system and payload.is_active is False:
            raise PermissionDeniedError("System accounts cannot be deactivated.")
        return await self.repo.update(account, payload.model_dump(exclude_unset=True))

    async def search(self, company_id: UUID, **kwargs: Any):
        return await self.repo.search(company_id=company_id, **kwargs)

    async def get_with_balance(self, account_id: UUID, company_id: UUID) -> Account:
        account = await self.repo.get_or_raise(account_id)
        balance, btype = await self.repo.get_balance(account_id)
        account.current_balance = balance  # type: ignore[attr-defined]
        account.balance_type = btype       # type: ignore[attr-defined]
        return account

    async def get_ledger(
        self, account_id: UUID, company_id: UUID,
        from_date: date | None, to_date: date | None,
        page: int, page_size: int,
    ) -> LedgerOut:
        account = await self.repo.get_or_raise(account_id)
        if account.company_id != company_id:
            raise PermissionDeniedError()

        ledger_repo = AccountLedgerRepository(self.repo.session)

        # Opening balance = the account's base opening balance, adjusted for
        # every ledger entry that happened strictly before the from_date filter
        opening = account.opening_balance if account.opening_balance_type == "Dr" else -account.opening_balance
        if from_date:
            prior_stmt = select(
                func.coalesce(func.sum(AccountLedger.debit_amount), 0),
                func.coalesce(func.sum(AccountLedger.credit_amount), 0),
            ).where(
                AccountLedger.company_id == company_id,
                AccountLedger.account_id == account_id,
                AccountLedger.txn_date < from_date,
            )
            prior_dr, prior_cr = (await self.repo.session.execute(prior_stmt)).one()
            opening += Decimal(prior_dr) - Decimal(prior_cr)

        # Period totals — computed across the FULL date range, not just the current page
        period_stmt = select(
            func.coalesce(func.sum(AccountLedger.debit_amount), 0),
            func.coalesce(func.sum(AccountLedger.credit_amount), 0),
        ).where(
            AccountLedger.company_id == company_id,
            AccountLedger.account_id == account_id,
        )
        if from_date:
            period_stmt = period_stmt.where(AccountLedger.txn_date >= from_date)
        if to_date:
            period_stmt = period_stmt.where(AccountLedger.txn_date <= to_date)
        period_dr, period_cr = (await self.repo.session.execute(period_stmt)).one()
        period_dr, period_cr = Decimal(period_dr), Decimal(period_cr)

        closing = opening + period_dr - period_cr

        result = await ledger_repo.get_ledger(company_id, account_id, from_date, to_date, page, page_size)

        return LedgerOut(
            account_id=account.id,
            account_code=account.account_code,
            account_name=account.account_name,
            opening_balance=abs(opening),
            opening_balance_type="Dr" if opening >= 0 else "Cr",
            total_debit=period_dr,
            total_credit=period_cr,
            closing_balance=abs(closing),
            closing_balance_type="Dr" if closing >= 0 else "Cr",
            entries=[LedgerEntryOut.model_validate(e) for e in result.items],
            total=result.total, page=result.page, page_size=result.page_size, pages=result.pages,
        )

    async def seed_default_accounts(self, company_id: UUID, user_id: UUID) -> None:
        """
        Seed system Chart of Accounts for a new company.
        Groups: Assets, Liabilities, Income, Expenses, Equity.
        """
        groups_seed = [
            # code, name, nature, parent=None
            ("A", "Assets",           "asset",     None),
            ("A01", "Current Assets", "asset",     "A"),
            ("A01-CASH", "Cash in Hand", "asset",  "A01"),
            ("A01-BANK", "Bank Accounts", "asset", "A01"),
            ("A01-RECV", "Sundry Debtors", "asset","A01"),
            ("A01-ADV",  "Advances",    "asset",   "A01"),
            ("A02", "Fixed Assets",    "asset",     "A"),
            ("L", "Liabilities",       "liability", None),
            ("L01", "Current Liabilities","liability","L"),
            ("L01-PABL", "Sundry Creditors","liability","L01"),
            ("L01-GST",  "GST Liabilities","liability","L01"),
            ("L01-TDS",  "TDS Payable","liability", "L01"),
            ("L02", "Long Term Liabilities","liability","L"),
            ("E", "Equity",            "equity",    None),
            ("E01", "Capital Account", "equity",    "E"),
            ("E02", "Reserves",        "equity",    "E"),
            ("I", "Income",            "income",    None),
            ("I01", "Sales Revenue",   "income",    "I"),
            ("I02", "Other Income",    "income",    "I"),
            ("EX", "Expenses",         "expense",   None),
            ("EX01", "Purchase Accounts","expense", "EX"),
            ("EX02", "Direct Expenses","expense",   "EX"),
            ("EX03", "Indirect Expenses","expense", "EX"),
        ]
        code_to_id: dict[str, UUID] = {}
        for code, name, nature, parent_code in groups_seed:
            existing = await self.group_repo.get_by(company_id=company_id, group_code=code)
            if not existing:
                grp = await self.group_repo.create({
                    "company_id": company_id,
                    "group_code": code,
                    "group_name": name,
                    "nature": nature,
                    "parent_group_id": code_to_id.get(parent_code) if parent_code else None,
                    "is_system": True,
                })
                code_to_id[code] = grp.id
            else:
                code_to_id[code] = existing.id

        # Seed leaf accounts
        accounts_seed = [
            ("1001", "Cash",             "cash",     "A01-CASH"),
            ("2001", "State Bank (Main)","bank",     "A01-BANK"),
            ("3001", "Sundry Debtors",   "receivable","A01-RECV"),
            ("4001", "Sundry Creditors", "payable",  "L01-PABL"),
            ("5001", "CGST Input",       "gst_input","A01"),
            ("5002", "SGST Input",       "gst_input","A01"),
            ("5003", "IGST Input",       "gst_input","A01"),
            ("5004", "CGST Output",      "gst_output","L01-GST"),
            ("5005", "SGST Output",      "gst_output","L01-GST"),
            ("5006", "IGST Output",      "gst_output","L01-GST"),
            ("6001", "Sales",            "income",   "I01"),
            ("6002", "Sales Returns",    "income",   "I01"),
            ("7001", "Purchase",         "expense",  "EX01"),
            ("7002", "Purchase Returns", "expense",  "EX01"),
            ("8001", "Capital Account",  "equity",   "E01"),
            ("9001", "TDS Payable",      "tds_payable","L01-TDS"),
        ]
        for code, name, atype, group_code in accounts_seed:
            existing = await self.repo.get_by(company_id=company_id, account_code=code)
            if not existing:
                await self.repo.create({
                    "company_id": company_id,
                    "group_id": code_to_id[group_code],
                    "account_code": code,
                    "account_name": name,
                    "account_type": atype,
                    "is_system": True,
                    "created_by": user_id,
                })


# ═══════════════════════════════════════════════════════════════════
# JOURNAL VOUCHER SERVICE
# ═══════════════════════════════════════════════════════════════════

class JournalVoucherService:
    def __init__(self, session: AsyncSession) -> None:
        self.jv_repo = JournalVoucherRepository(session)
        self.ledger_repo = AccountLedgerRepository(session)
        self.fy_repo = FinancialYearRepository(session)
        self.session = session

    async def _next_jv_no(self, company_id: UUID, jv_type: str) -> str:
        prefix_map = {
            "payment": "PV", "receipt": "RV", "contra": "CV",
            "journal": "JV", "purchase": "PB", "sale": "SV",
            "debit_note": "DN", "credit_note": "CN",
            "opening": "OB", "closing": "CB", "depreciation": "DEP",
        }
        prefix = prefix_map.get(jv_type, "JV")
        stmt = text("""
            SELECT COUNT(*)+1 FROM journal_vouchers
            WHERE company_id=:cid AND jv_type=:jtype
        """)
        count = (await self.session.execute(stmt, {"cid": str(company_id), "jtype": jv_type})).scalar_one()
        return f"{prefix}-{str(count).zfill(5)}"

    async def create(
        self,
        company_id: UUID,
        payload: JournalVoucherCreate,
        user_id: UUID,
        branch_id: UUID | None = None,
    ) -> JournalVoucher:
        # Lock check
        fy = await self.fy_repo.get_current(company_id)
        if fy and fy.is_locked:
            if fy.start_date <= payload.jv_date <= fy.end_date:
                raise BusinessError("Financial year is locked. No posting allowed.")

        jv_no = await self._next_jv_no(company_id, payload.jv_type)
        total_dr = sum(e.debit_amount for e in payload.entries)
        total_cr = sum(e.credit_amount for e in payload.entries)

        jv = await self.jv_repo.create({
            "company_id": company_id,
            "branch_id": branch_id,
            "jv_no": jv_no,
            "jv_type": payload.jv_type,
            "jv_date": payload.jv_date,
            "narration": payload.narration,
            "ref_type": payload.ref_type,
            "ref_id": payload.ref_id,
            "ref_no": payload.ref_no,
            "total_debit": total_dr,
            "total_credit": total_cr,
            "financial_year": _fy_code(payload.jv_date),
            "period": _period_code(payload.jv_date),
            "cost_center_id": payload.cost_center_id,
            "created_by": user_id,
        })

        for order, entry in enumerate(payload.entries):
            self.session.add(JournalEntry(
                jv_id=jv.id,
                account_id=entry.account_id,
                debit_amount=entry.debit_amount,
                credit_amount=entry.credit_amount,
                narration=entry.narration,
                party_id=entry.party_id,
                cost_center_id=entry.cost_center_id,
                display_order=order,
            ))
        await self.session.flush()
        return await self.jv_repo.get_with_entries(jv.id)  # type: ignore[return-value]

    async def post(self, jv_id: UUID, company_id: UUID, user_id: UUID) -> JournalVoucher:
        """Post JV → write AccountLedger rows with running balance."""
        jv = await self.jv_repo.get_with_entries(jv_id)
        if not jv:
            raise NotFoundError("Journal voucher not found.")
        if jv.company_id != company_id:
            raise PermissionDeniedError()
        if jv.is_posted:
            raise BusinessError("Voucher is already posted.")

        for entry in jv.entries:
            # Get last running balance for this account
            last = await self.session.execute(
                select(AccountLedger)
                .join(JournalVoucher, JournalVoucher.id == AccountLedger.jv_id)
                .where(AccountLedger.account_id == entry.account_id,
                       AccountLedger.company_id == company_id)
                .order_by(AccountLedger.txn_date.desc(), JournalVoucher.created_at.desc())
                .limit(1)
            )
            last_row = last.scalar_one_or_none()
            prev_balance = last_row.running_balance if last_row else Decimal("0")
            prev_type = last_row.balance_type if last_row else "Dr"

            # Use one consistent signed convention: positive = Dr, negative = Cr
            prev_signed = prev_balance if prev_type == "Dr" else -prev_balance
            net = entry.debit_amount - entry.credit_amount
            new_signed = prev_signed + net
            balance_type = "Dr" if new_signed >= 0 else "Cr"
            new_balance = abs(new_signed)

            self.session.add(AccountLedger(
                company_id=company_id,
                account_id=entry.account_id,
                jv_id=jv.id,
                entry_id=entry.id,
                txn_date=jv.jv_date,
                jv_no=jv.jv_no,
                jv_type=jv.jv_type,
                ref_type=jv.ref_type,
                ref_no=jv.ref_no,
                debit_amount=entry.debit_amount,
                credit_amount=entry.credit_amount,
                running_balance=abs(new_balance),
                balance_type=balance_type,
                narration=entry.narration or jv.narration,
                party_id=entry.party_id,
                cost_center_id=entry.cost_center_id,
                financial_year=jv.financial_year,
                period=jv.period,
            ))

        await self.jv_repo.post(jv_id, user_id)
        await self.session.flush()
        return await self.jv_repo.get_with_entries(jv_id)  # type: ignore[return-value]

    async def reverse(self, jv_id: UUID, company_id: UUID, user_id: UUID) -> JournalVoucher:
        """Create a mirror-image JV to reverse a posted voucher."""
        original = await self.jv_repo.get_with_entries(jv_id)
        if not original or not original.is_posted:
            raise BusinessError("Only posted vouchers can be reversed.")
        if original.is_reversed:
            raise BusinessError("Voucher is already reversed.")

        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate
        rev_entries = [
            JournalEntryLine(
                account_id=e.account_id,
                debit_amount=e.credit_amount,
                credit_amount=e.debit_amount,
                narration=f"Reversal: {e.narration or ''}",
                party_id=e.party_id,
            )
            for e in original.entries
        ]
        rev_payload = JournalVoucherCreate(
            jv_type=original.jv_type,
            jv_date=date.today(),
            narration=f"Reversal of {original.jv_no}",
            ref_type="reversal",
            ref_no=original.jv_no,
            entries=rev_entries,
        )
        rev_jv = await self.create(company_id, rev_payload, user_id)
        rev_jv = await self.post(rev_jv.id, company_id, user_id)
        # Mark original as reversed
        await self.jv_repo.update(original, {"is_reversed": True, "reversed_jv_id": rev_jv.id})
        return rev_jv

    # ── Convenience vouchers ────────────────────────────────────────

    async def create_payment(
        self,
        company_id: UUID,
        payload: PaymentVoucherCreate,
        user_id: UUID,
    ) -> JournalVoucher:
        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate
        jv_payload = JournalVoucherCreate(
            jv_type="payment",
            jv_date=payload.voucher_date,
            narration=payload.narration or "Payment",
            ref_no=payload.ref_no,
            entries=[
                JournalEntryLine(
                    account_id=payload.pay_to_account_id,
                    debit_amount=payload.amount,
                    party_id=payload.party_id,
                ),
                JournalEntryLine(
                    account_id=payload.pay_from_account_id,
                    credit_amount=payload.amount,
                ),
            ],
        )
        jv = await self.create(company_id, jv_payload, user_id)
        return await self.post(jv.id, company_id, user_id)

    async def create_receipt(
        self,
        company_id: UUID,
        payload: ReceiptVoucherCreate,
        user_id: UUID,
    ) -> JournalVoucher:
        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate
        jv_payload = JournalVoucherCreate(
            jv_type="receipt",
            jv_date=payload.voucher_date,
            narration=payload.narration or "Receipt",
            ref_no=payload.ref_no,
            entries=[
                JournalEntryLine(
                    account_id=payload.receive_in_account_id,
                    debit_amount=payload.amount,
                ),
                JournalEntryLine(
                    account_id=payload.receive_from_account_id,
                    credit_amount=payload.amount,
                    party_id=payload.party_id,
                ),
            ],
        )
        jv = await self.create(company_id, jv_payload, user_id)
        return await self.post(jv.id, company_id, user_id)

    async def create_contra(
        self,
        company_id: UUID,
        payload: ContraVoucherCreate,
        user_id: UUID,
    ) -> JournalVoucher:
        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate
        jv_payload = JournalVoucherCreate(
            jv_type="contra",
            jv_date=payload.voucher_date,
            narration=payload.narration or "Contra",
            entries=[
                JournalEntryLine(
                    account_id=payload.to_account_id,
                    debit_amount=payload.amount,
                ),
                JournalEntryLine(
                    account_id=payload.from_account_id,
                    credit_amount=payload.amount,
                ),
            ],
        )
        jv = await self.create(company_id, jv_payload, user_id)
        return await self.post(jv.id, company_id, user_id)


# ═══════════════════════════════════════════════════════════════════
# AUTOMATED ACCOUNTING FROM BILLING
# ═══════════════════════════════════════════════════════════════════

class AutoAccountingService:
    """
    Creates double-entry journal vouchers automatically when billing
    events occur (invoice finalized, payment recorded, etc.).
    Consumes the same JournalVoucherService so all rules apply.
    """
    def __init__(self, session: AsyncSession) -> None:
        self.jv_svc = JournalVoucherService(session)
        self.acct_repo = AccountRepository(session)

    async def _get_system_account(self, company_id: UUID, account_type: str, name_contains: str | None = None) -> Account:
        accounts = await self.acct_repo.get_by_type(company_id, account_type)
        if not accounts:
            raise BusinessError(
                f"No '{account_type}' account found. "
                "Please seed the chart of accounts first."
            )
        if name_contains:
            matched = [a for a in accounts if name_contains.lower() in a.account_name.lower()]
            if matched:
                return matched[0]
            raise BusinessError(
                f"No '{account_type}' account matching '{name_contains}' found among: "
                + ", ".join(a.account_name for a in accounts)
            )
        return accounts[0]

    async def on_invoice_finalized(
        self,
        company_id: UUID,
        invoice_id: UUID,
        invoice_no: str,
        invoice_date: date,
        party_id: UUID,
        taxable_amount: Decimal,
        cgst_amount: Decimal,
        sgst_amount: Decimal,
        igst_amount: Decimal,
        total_amount: Decimal,
        supply_type: str,
        user_id: UUID,
        invoice_type: str = "tax_invoice",
    ) -> JournalVoucher:
        """
        Normal sale: Dr Debtor, Cr Sales + Cr GST Output.
        Credit note (Sales Return): the exact reverse — Cr Debtor, Dr Sales Returns + Dr GST Output.
        """
        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate

        is_return = invoice_type == "credit_note"

        debtor = await self._get_system_account(company_id, "receivable")
        sales  = (await self._get_system_account(company_id, "income", "Returns")) if is_return \
                 else (await self._get_system_account(company_id, "income"))
        cgst_o = await self._get_system_account(company_id, "gst_output", "CGST")
        sgst_o = await self._get_system_account(company_id, "gst_output", "SGST")
        igst_o = await self._get_system_account(company_id, "gst_output", "IGST")

        if is_return:
            entries = [
                JournalEntryLine(account_id=debtor.id, credit_amount=total_amount, party_id=party_id),
                JournalEntryLine(account_id=sales.id,  debit_amount=taxable_amount),
            ]
        else:
            entries = [
                JournalEntryLine(account_id=debtor.id, debit_amount=total_amount, party_id=party_id),
                JournalEntryLine(account_id=sales.id,  credit_amount=taxable_amount),
            ]

        is_igst = supply_type == "inter" and igst_amount > 0
        gst_side = "debit_amount" if is_return else "credit_amount"
        if is_igst:
            if igst_amount > 0:
                entries.append(JournalEntryLine(account_id=igst_o.id, **{gst_side: igst_amount}))
        else:
            if cgst_amount > 0:
                entries.append(JournalEntryLine(account_id=cgst_o.id, **{gst_side: cgst_amount}))
            if sgst_amount > 0:
                entries.append(JournalEntryLine(account_id=sgst_o.id, **{gst_side: sgst_amount}))

        payload = JournalVoucherCreate(
            jv_type="credit_note" if is_return else "sale",
            jv_date=invoice_date,
            narration=f"{'Sales Return' if is_return else 'Sales Invoice'} {invoice_no}",
            ref_type="invoice",
            ref_id=invoice_id,
            ref_no=invoice_no,
            entries=entries,
        )
        jv = await self.jv_svc.create(company_id, payload, user_id)
        return await self.jv_svc.post(jv.id, company_id, user_id)

    async def on_payment_received(
        self,
        company_id: UUID,
        payment_id: UUID,
        payment_no: str,
        payment_date: date,
        party_id: UUID,
        amount: Decimal,
        payment_method: str,
        user_id: UUID,
    ) -> JournalVoucher:
        """Dr Cash/Bank, Cr Debtor."""
        account_type = "bank" if payment_method != "cash" else "cash"
        cash_bank = await self._get_system_account(company_id, account_type)
        debtor    = await self._get_system_account(company_id, "receivable")
        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate
        payload = JournalVoucherCreate(
            jv_type="receipt",
            jv_date=payment_date,
            narration=f"Receipt {payment_no}",
            ref_type="payment",
            ref_id=payment_id,
            ref_no=payment_no,
            entries=[
                JournalEntryLine(account_id=cash_bank.id, debit_amount=amount),
                JournalEntryLine(account_id=debtor.id, credit_amount=amount, party_id=party_id),
            ],
        )
        jv = await self.jv_svc.create(company_id, payload, user_id)
        return await self.jv_svc.post(jv.id, company_id, user_id)

    async def on_payment_made(
        self,
        company_id: UUID,
        payment_id: UUID,
        payment_no: str,
        payment_date: date,
        party_id: UUID,
        amount: Decimal,
        payment_method: str,
        user_id: UUID,
    ) -> JournalVoucher:
        """Dr Creditor, Cr Cash/Bank — the reverse of on_payment_received."""
        account_type = "bank" if payment_method != "cash" else "cash"
        cash_bank = await self._get_system_account(company_id, account_type)
        creditor  = await self._get_system_account(company_id, "payable")
        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate
        payload = JournalVoucherCreate(
            jv_type="payment",
            jv_date=payment_date,
            narration=f"Payment {payment_no}",
            ref_type="payment",
            ref_id=payment_id,
            ref_no=payment_no,
            entries=[
                JournalEntryLine(account_id=creditor.id, debit_amount=amount, party_id=party_id),
                JournalEntryLine(account_id=cash_bank.id, credit_amount=amount),
            ],
        )
        jv = await self.jv_svc.create(company_id, payload, user_id)
        return await self.jv_svc.post(jv.id, company_id, user_id)

    async def on_purchase_bill_created(
        self,
        company_id: UUID,
        bill_id: UUID,
        bill_no: str,
        bill_date: date,
        vendor_id: UUID,
        taxable_amount: Decimal,
        cgst_amount: Decimal,
        sgst_amount: Decimal,
        igst_amount: Decimal,
        total_amount: Decimal,
        user_id: UUID,
    ) -> JournalVoucher:
        """Dr Purchase + Dr GST Input, Cr Creditor."""
        purchase  = await self._get_system_account(company_id, "expense")
        creditor  = await self._get_system_account(company_id, "payable")
        cgst_i = await self._get_system_account(company_id, "gst_input", "CGST")
        sgst_i = await self._get_system_account(company_id, "gst_input", "SGST")
        igst_i = await self._get_system_account(company_id, "gst_input", "IGST")
        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate
        entries = [
            JournalEntryLine(account_id=purchase.id, debit_amount=taxable_amount),
            JournalEntryLine(account_id=creditor.id, credit_amount=total_amount, party_id=vendor_id),
        ]
        if igst_amount > 0:
            entries.append(JournalEntryLine(account_id=igst_i.id, debit_amount=igst_amount))
        else:
            if cgst_amount > 0:
                entries.append(JournalEntryLine(account_id=cgst_i.id, debit_amount=cgst_amount))
            if sgst_amount > 0:
                entries.append(JournalEntryLine(account_id=sgst_i.id, debit_amount=sgst_amount))
        payload = JournalVoucherCreate(
            jv_type="purchase",
            jv_date=bill_date,
            narration=f"Purchase Bill {bill_no}",
            ref_type="purchase_bill",
            ref_id=bill_id,
            ref_no=bill_no,
            entries=entries,
        )
        jv = await self.jv_svc.create(company_id, payload, user_id)
        return await self.jv_svc.post(jv.id, company_id, user_id)

    async def on_purchase_return_created(
        self,
        company_id: UUID,
        return_ref_id: UUID,
        return_ref_no: str,
        return_date: date,
        vendor_id: UUID,
        taxable_amount: Decimal,
        cgst_amount: Decimal,
        sgst_amount: Decimal,
        igst_amount: Decimal,
        total_amount: Decimal,
        user_id: UUID,
    ) -> JournalVoucher:
        """Dr Creditor, Cr Purchase Returns + Cr GST Input — the reverse of on_purchase_bill_created."""
        from app.schemas.accounting import JournalEntryLine, JournalVoucherCreate
        creditor  = await self._get_system_account(company_id, "payable")
        purchase_r = await self._get_system_account(company_id, "expense", "Returns")
        cgst_i = await self._get_system_account(company_id, "gst_input", "CGST")
        sgst_i = await self._get_system_account(company_id, "gst_input", "SGST")
        igst_i = await self._get_system_account(company_id, "gst_input", "IGST")

        entries = [
            JournalEntryLine(account_id=creditor.id, debit_amount=total_amount, party_id=vendor_id),
            JournalEntryLine(account_id=purchase_r.id, credit_amount=taxable_amount),
        ]
        if igst_amount > 0:
            entries.append(JournalEntryLine(account_id=igst_i.id, credit_amount=igst_amount))
        else:
            if cgst_amount > 0:
                entries.append(JournalEntryLine(account_id=cgst_i.id, credit_amount=cgst_amount))
            if sgst_amount > 0:
                entries.append(JournalEntryLine(account_id=sgst_i.id, credit_amount=sgst_amount))

        payload = JournalVoucherCreate(
            jv_type="debit_note",
            jv_date=return_date,
            narration=f"Purchase Return {return_ref_no}",
            ref_type="purchase_order",
            ref_id=return_ref_id,
            ref_no=return_ref_no,
            entries=entries,
        )
        jv = await self.jv_svc.create(company_id, payload, user_id)
        return await self.jv_svc.post(jv.id, company_id, user_id)


# ═══════════════════════════════════════════════════════════════════
# REPORTS SERVICE
# ═══════════════════════════════════════════════════════════════════

class AccountingReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.acct_repo = AccountRepository(session)
        self.group_repo = AccountGroupRepository(session)
        self.ledger_repo = AccountLedgerRepository(session)
        self.session = session

    async def trial_balance(
        self,
        company_id: UUID,
        from_date: date,
        to_date: date,
    ) -> TrialBalanceOut:
        """Compute trial balance for a date range."""
        # All accounts
        stmt = select(Account).where(Account.company_id == company_id, Account.is_active == True)
        accounts_result = await self.session.execute(
            stmt.options(__import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(Account.group))
        )
        accounts = accounts_result.scalars().all()

        # Debit / credit totals per account for the period
        period_stmt = text("""
            SELECT account_id,
                   COALESCE(SUM(debit_amount),0)  AS period_dr,
                   COALESCE(SUM(credit_amount),0) AS period_cr
            FROM account_ledger
            WHERE company_id = :cid
              AND txn_date BETWEEN :from_d AND :to_d
            GROUP BY account_id
        """)
        period_rows = (await self.session.execute(
            period_stmt, {"cid": str(company_id), "from_d": from_date, "to_d": to_date}
        )).mappings().all()
        period_map = {UUID(str(r["account_id"])): r for r in period_rows}

        # Opening balance before from_date
        open_stmt = text("""
            SELECT account_id,
                   COALESCE(SUM(debit_amount),0)  AS open_dr,
                   COALESCE(SUM(credit_amount),0) AS open_cr
            FROM account_ledger
            WHERE company_id = :cid AND txn_date < :from_d
            GROUP BY account_id
        """)
        open_rows = (await self.session.execute(
            open_stmt, {"cid": str(company_id), "from_d": from_date}
        )).mappings().all()
        open_map = {UUID(str(r["account_id"])): r for r in open_rows}

        rows: list[TrialBalanceRow] = []
        total_dr = Decimal("0")
        total_cr = Decimal("0")

        for acct in accounts:
            p = period_map.get(acct.id, {})
            o = open_map.get(acct.id, {})
            o_dr = Decimal(str(o.get("open_dr", 0)))
            o_cr = Decimal(str(o.get("open_cr", 0)))
            # NEW — fold in the account's base opening balance (set at account
            # creation, representing balance before any ledger postings existed)
            if acct.opening_balance_type == "Dr":
                o_dr += acct.opening_balance
            else:
                o_cr += acct.opening_balance
            p_dr = Decimal(str(p.get("period_dr", 0)))
            p_cr = Decimal(str(p.get("period_cr", 0)))
            c_dr = o_dr + p_dr
            c_cr = o_cr + p_cr
            if c_dr == 0 and c_cr == 0:
                continue
            rows.append(TrialBalanceRow(
                account_id=acct.id,
                account_code=acct.account_code,
                account_name=acct.account_name,
                account_type=acct.account_type,
                group_name=acct.group.group_name if acct.group else "",
                opening_dr=o_dr, opening_cr=o_cr,
                period_dr=p_dr, period_cr=p_cr,
                closing_dr=c_dr, closing_cr=c_cr,
            ))
            total_dr += c_dr
            total_cr += c_cr

        rows.sort(key=lambda r: r.account_code)
        return TrialBalanceOut(
            company_id=company_id,
            from_date=from_date,
            to_date=to_date,
            rows=rows,
            total_dr=total_dr,
            total_cr=total_cr,
            is_balanced=(abs(total_dr - total_cr) < Decimal("0.05")),
        )

    async def profit_and_loss(
        self,
        company_id: UUID,
        from_date: date,
        to_date: date,
    ) -> ProfitLossOut:
        """Compute P&L from ledger entries."""
        stmt = text("""
            SELECT a.account_type, a.account_name, a.account_code,
                   ag.affects_gross_profit,
                   COALESCE(SUM(al.credit_amount - al.debit_amount), 0) AS net
            FROM account_ledger al
            JOIN accounts a ON a.id = al.account_id
            JOIN account_groups ag ON ag.id = a.group_id
            WHERE al.company_id = :cid
              AND al.txn_date BETWEEN :from_d AND :to_d
              AND ag.nature IN ('income','expense')
            GROUP BY a.account_type, a.account_name, a.account_code, ag.affects_gross_profit
            ORDER BY ag.affects_gross_profit DESC, a.account_code
        """)
        rows_raw = (await self.session.execute(
            stmt, {"cid": str(company_id), "from_d": from_date, "to_d": to_date}
        )).mappings().all()

        income_rows: list[PLRow] = []
        expense_rows: list[PLRow] = []
        total_income = Decimal("0")
        total_expense = Decimal("0")
        gross_income = Decimal("0")
        gross_expense = Decimal("0")

        for r in rows_raw:
            net = Decimal(str(r["net"]))
            row = PLRow(label=r["account_name"], amount=abs(net))
            if r["account_type"] in ("income",) or net > 0:
                income_rows.append(row)
                total_income += abs(net)
                if r["affects_gross_profit"]:
                    gross_income += abs(net)
            else:
                row.amount = abs(net)
                expense_rows.append(row)
                total_expense += abs(net)
                if r["affects_gross_profit"]:
                    gross_expense += abs(net)

        gross_profit = gross_income - gross_expense
        net_profit = total_income - total_expense

        pl_rows = [
            PLRow(label="Income", amount=total_income, is_heading=True, children=income_rows),
            PLRow(label="Expenses", amount=total_expense, is_heading=True, children=expense_rows),
        ]
        return ProfitLossOut(
            company_id=company_id,
            from_date=from_date,
            to_date=to_date,
            gross_profit=gross_profit,
            operating_profit=net_profit,
            net_profit=net_profit,
            rows=pl_rows,
        )

    async def balance_sheet(self, company_id: UUID, as_of_date: date) -> BalanceSheetOut:
        """Compute Balance Sheet as of a given date."""
        stmt = text("""
            SELECT a.id, a.account_name, a.account_code, a.account_type,
                   a.opening_balance, a.opening_balance_type, ag.nature,
                   COALESCE(SUM(al.debit_amount - al.credit_amount)
                            FILTER (WHERE al.txn_date <= :as_of), 0) AS ledger_net_dr
            FROM accounts a
            JOIN account_groups ag ON ag.id = a.group_id
            LEFT JOIN account_ledger al
                   ON al.account_id = a.id AND al.company_id = a.company_id
            WHERE a.company_id = :cid AND a.is_active = true
              AND ag.nature IN ('asset','liability','equity')
            GROUP BY a.id, a.account_name, a.account_code, a.account_type,
                     a.opening_balance, a.opening_balance_type, ag.nature
            ORDER BY ag.nature, a.account_code
        """)
        rows_raw = (await self.session.execute(
            stmt, {"cid": str(company_id), "as_of": as_of_date}
        )).mappings().all()

        assets: list[BalanceSheetRow] = []
        liabilities: list[BalanceSheetRow] = []
        total_assets = Decimal("0")
        total_liabilities = Decimal("0")

        for r in rows_raw:
            ledger_net = Decimal(str(r["ledger_net_dr"]))
            opening = r["opening_balance"] if r["opening_balance_type"] == "Dr" else -r["opening_balance"]
            net = opening + ledger_net  # signed: positive = Dr, negative = Cr
            if net == 0:
                continue
            if r["nature"] == "asset":
                # Assets normally carry a Dr balance — report the signed value directly,
                # so an abnormal Cr balance (e.g. an overdrawn bank account) correctly
                # REDUCES total assets instead of being added as if it were positive.
                assets.append(BalanceSheetRow(label=r["account_name"], amount=net))
                total_assets += net
            else:
                # Liabilities/Equity normally carry a Cr balance (negative in this
                # convention) — flip sign so a normal liability displays as positive.
                liabilities.append(BalanceSheetRow(label=r["account_name"], amount=-net))
                total_liabilities += -net

        # NEW — fold in accumulated (not-yet-closed) Net Profit as a synthetic
        # equity line. Without this, an interim Balance Sheet can never actually
        # balance against the P&L — this mirrors how real accounting software
        # (e.g. Tally) shows a running "Profit & Loss A/c" line under
        # Liabilities & Equity until a formal year-end closing entry is passed.
        pl = await self.profit_and_loss(company_id, date(1900, 1, 1), as_of_date)
        if pl.net_profit != 0:
            label = "Profit & Loss A/c (Current Year)" if pl.net_profit >= 0 else "Accumulated Loss"
            liabilities.append(BalanceSheetRow(label=label, amount=pl.net_profit))
            total_liabilities += pl.net_profit

        net_worth = total_assets - total_liabilities
        return BalanceSheetOut(
            company_id=company_id,
            as_of_date=as_of_date,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            net_worth=net_worth,
            assets=assets,
            liabilities=liabilities,
        )


# ═══════════════════════════════════════════════════════════════════
# GST REPORT SERVICE
# ═══════════════════════════════════════════════════════════════════

class GSTReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.gst_repo = GSTReturnRepository(session)

    async def gstr1_data(self, company_id: UUID, from_date: date, to_date: date) -> list[GSTR1Row]:
        """Pull all B2B/B2C invoice data for GSTR-1."""
        stmt = text("""
            SELECT
                i.invoice_no, i.invoice_date, i.billing_name AS party_name,
                i.billing_gstin AS party_gstin, i.place_of_supply,
                i.supply_type, i.taxable_amount, i.cgst_amount, i.sgst_amount,
                i.igst_amount, i.cess_amount, i.total_amount, i.invoice_type
            FROM invoices i
            WHERE i.company_id = :cid
              AND i.invoice_date BETWEEN :from_d AND :to_d
              AND i.status NOT IN ('cancelled','void','draft')
            ORDER BY i.invoice_date, i.invoice_no
        """)
        rows = (await self.session.execute(
            stmt, {"cid": str(company_id), "from_d": from_date, "to_d": to_date}
        )).mappings().all()
        return [GSTR1Row(**dict(r)) for r in rows]

    async def gstr3b_summary(self, company_id: UUID, from_date: date, to_date: date) -> list[GSTR3BRow]:
        """Compute GSTR-3B table 3.1 outward supply summary."""
        stmt = text("""
            SELECT
                CASE supply_type
                    WHEN 'inter' THEN 'Outward taxable supplies (other than zero rated, nil rated and exempted)'
                    WHEN 'intra' THEN 'Outward taxable supplies (intra-state)'
                    ELSE 'Other'
                END AS description,
                SUM(taxable_amount) AS taxable_amount,
                SUM(igst_amount)    AS integrated_tax,
                SUM(cgst_amount)    AS central_tax,
                SUM(sgst_amount)    AS state_tax,
                SUM(cess_amount)    AS cess
            FROM invoices
            WHERE company_id = :cid
              AND invoice_date BETWEEN :from_d AND :to_d
              AND status NOT IN ('cancelled','void','draft')
            GROUP BY supply_type
        """)
        rows = (await self.session.execute(
            stmt, {"cid": str(company_id), "from_d": from_date, "to_d": to_date}
        )).mappings().all()
        return [GSTR3BRow(**dict(r)) for r in rows]

    async def compute_and_save_return(
        self,
        company_id: UUID,
        return_type: str,
        from_date: date,
        to_date: date,
        user_id: UUID,
    ) -> GSTReturn:
        from app.db.models.accounting import GSTReturn as GSTReturnModel
        from datetime import date as dt

        existing = await self.gst_repo.get_by_period(company_id, return_type, from_date)
        if existing and existing.status == "filed":
            raise BusinessError("This return has already been filed.")

        # Aggregate output GST from invoices
        out_stmt = text("""
            SELECT
                COALESCE(SUM(taxable_amount),0)  AS taxable,
                COALESCE(SUM(cgst_amount),0)     AS cgst,
                COALESCE(SUM(sgst_amount),0)     AS sgst,
                COALESCE(SUM(igst_amount),0)     AS igst,
                COALESCE(SUM(cess_amount),0)     AS cess
            FROM invoices
            WHERE company_id = :cid
              AND invoice_date BETWEEN :from_d AND :to_d
              AND status NOT IN ('cancelled','void','draft')
        """)
        out = (await self.session.execute(
            out_stmt, {"cid": str(company_id), "from_d": from_date, "to_d": to_date}
        )).mappings().one()

        # ITC from purchase bills
        itc_stmt = text("""
            SELECT
                COALESCE(SUM(cgst_amount),0) AS itc_cgst,
                COALESCE(SUM(sgst_amount),0) AS itc_sgst,
                COALESCE(SUM(igst_amount),0) AS itc_igst
            FROM purchase_bills
            WHERE company_id = :cid
              AND bill_date BETWEEN :from_d AND :to_d
              AND status NOT IN ('cancelled')
        """)
        itc = (await self.session.execute(
            itc_stmt, {"cid": str(company_id), "from_d": from_date, "to_d": to_date}
        )).mappings().one()

        net_cgst = max(Decimal(str(out["cgst"])) - Decimal(str(itc["itc_cgst"])), Decimal("0"))
        net_sgst = max(Decimal(str(out["sgst"])) - Decimal(str(itc["itc_sgst"])), Decimal("0"))
        net_igst = max(Decimal(str(out["igst"])) - Decimal(str(itc["itc_igst"])), Decimal("0"))

        data = {
            "company_id": company_id,
            "return_type": return_type,
            "period_from": from_date,
            "period_to": to_date,
            "financial_year": _fy_code(from_date),
            "taxable_turnover": Decimal(str(out["taxable"])),
            "total_cgst_output": Decimal(str(out["cgst"])),
            "total_sgst_output": Decimal(str(out["sgst"])),
            "total_igst_output": Decimal(str(out["igst"])),
            "itc_cgst": Decimal(str(itc["itc_cgst"])),
            "itc_sgst": Decimal(str(itc["itc_sgst"])),
            "itc_igst": Decimal(str(itc["itc_igst"])),
            "net_cgst_payable": net_cgst,
            "net_sgst_payable": net_sgst,
            "net_igst_payable": net_igst,
            "total_tax_payable": net_cgst + net_sgst + net_igst,
            "status": "prepared",
        }
        if existing:
            return await self.gst_repo.update(existing, data)
        return await self.gst_repo.create(data)
