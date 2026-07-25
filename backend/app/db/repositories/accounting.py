"""
VyaparPro — Accounting Repositories
Typed query helpers for every accounting entity.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import selectinload

from app.db.models.accounting import (
    Account, AccountGroup, AccountLedger, BankReconciliation,
    CostCenter, FinancialYear, GSTReturn, ITCLedger,
    JournalEntry, JournalVoucher,
)
from app.db.repositories.base import BaseRepository, Pagination


# ── Account Groups ────────────────────────────────────────────────────────────

class AccountGroupRepository(BaseRepository[AccountGroup]):
    model = AccountGroup

    async def get_tree(self, company_id: UUID) -> list[AccountGroup]:
        stmt = (
            select(AccountGroup)
            .where(AccountGroup.company_id == company_id, AccountGroup.is_active == True)
            .order_by(AccountGroup.display_order, AccountGroup.group_name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_nature(self, company_id: UUID, nature: str) -> list[AccountGroup]:
        stmt = (
            select(AccountGroup)
            .where(AccountGroup.company_id == company_id, AccountGroup.nature == nature)
            .order_by(AccountGroup.display_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── Chart of Accounts ─────────────────────────────────────────────────────────

class AccountRepository(BaseRepository[Account]):
    model = Account

    async def get_by_type(self, company_id: UUID, account_type: str) -> list[Account]:
        stmt = (
            select(Account)
            .where(Account.company_id == company_id,
                   Account.account_type == account_type,
                   Account.is_active == True)
            .order_by(Account.account_name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_cash_accounts(self, company_id: UUID) -> list[Account]:
        return await self.get_by_type(company_id, "cash")

    async def get_bank_accounts(self, company_id: UUID) -> list[Account]:
        return await self.get_by_type(company_id, "bank")

    async def search(
        self,
        company_id: UUID,
        query: str | None = None,
        account_type: str | None = None,
        group_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Pagination:
        stmt = (
            select(Account)
            .where(Account.company_id == company_id, Account.is_active == True)
            .options(selectinload(Account.group))
        )
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(Account.account_name.ilike(like), Account.account_code.ilike(like))
            )
        if account_type:
            stmt = stmt.where(Account.account_type == account_type)
        if group_id:
            stmt = stmt.where(Account.group_id == group_id)
        stmt = stmt.order_by(Account.account_code)
        return await self.paginate(stmt, page, page_size)

    async def get_balance(self, account_id: UUID) -> tuple[Decimal, str]:
        """Return (balance_amount, Dr|Cr) from account_ledger."""
        stmt = (
            select(
                func.coalesce(func.sum(AccountLedger.debit_amount), 0).label("total_dr"),
                func.coalesce(func.sum(AccountLedger.credit_amount), 0).label("total_cr"),
            )
            .where(AccountLedger.account_id == account_id)
        )
        row = (await self.session.execute(stmt)).one()
        dr, cr = Decimal(str(row.total_dr)), Decimal(str(row.total_cr))
        if dr >= cr:
            return (dr - cr, "Dr")
        return (cr - dr, "Cr")

    async def get_balances_bulk(self, company_id: UUID) -> dict[UUID, tuple[Decimal, str]]:
        """Fetch all account balances in one query for trial balance."""
        stmt = (
            select(
                AccountLedger.account_id,
                func.coalesce(func.sum(AccountLedger.debit_amount), 0).label("total_dr"),
                func.coalesce(func.sum(AccountLedger.credit_amount), 0).label("total_cr"),
            )
            .where(AccountLedger.company_id == company_id)
            .group_by(AccountLedger.account_id)
        )
        rows = (await self.session.execute(stmt)).all()
        result: dict[UUID, tuple[Decimal, str]] = {}
        for row in rows:
            dr, cr = Decimal(str(row.total_dr)), Decimal(str(row.total_cr))
            if dr >= cr:
                result[row.account_id] = (dr - cr, "Dr")
            else:
                result[row.account_id] = (cr - dr, "Cr")
        return result


# ── Journal Vouchers ──────────────────────────────────────────────────────────

class JournalVoucherRepository(BaseRepository[JournalVoucher]):
    model = JournalVoucher

    async def get_with_entries(self, jv_id: UUID) -> JournalVoucher | None:
        stmt = (
            select(JournalVoucher)
            .where(JournalVoucher.id == jv_id)
            .options(
                selectinload(JournalVoucher.entries)
                .selectinload(JournalEntry.account)
                .selectinload(Account.group)
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    async def search(
        self,
        company_id: UUID,
        jv_type: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        ref_no: str | None = None,
        is_posted: bool | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> Pagination:
        stmt = (
            select(JournalVoucher)
            .where(JournalVoucher.company_id == company_id)
            .options(
                selectinload(JournalVoucher.entries)
                .selectinload(JournalEntry.account)
                .selectinload(Account.group)
            )
        )
        if jv_type:
            stmt = stmt.where(JournalVoucher.jv_type == jv_type)
        if from_date:
            stmt = stmt.where(JournalVoucher.jv_date >= from_date)
        if to_date:
            stmt = stmt.where(JournalVoucher.jv_date <= to_date)
        if ref_no:
            stmt = stmt.where(JournalVoucher.ref_no.ilike(f"%{ref_no}%"))
        if is_posted is not None:
            stmt = stmt.where(JournalVoucher.is_posted == is_posted)
        stmt = stmt.order_by(JournalVoucher.jv_date.desc(), JournalVoucher.created_at.desc())
        return await self.paginate(stmt, page, page_size)

    async def get_by_ref(self, company_id: UUID, ref_type: str, ref_id: UUID) -> list[JournalVoucher]:
        stmt = (
            select(JournalVoucher)
            .where(
                JournalVoucher.company_id == company_id,
                JournalVoucher.ref_type == ref_type,
                JournalVoucher.ref_id == ref_id,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def post(self, jv_id: UUID, posted_by: UUID) -> None:
        from datetime import datetime, timezone
        await self.session.execute(
            update(JournalVoucher)
            .where(JournalVoucher.id == jv_id)
            .values(is_posted=True, posted_at=datetime.now(timezone.utc), posted_by=posted_by)
        )


# ── Account Ledger ─────────────────────────────────────────────────────────────

class AccountLedgerRepository(BaseRepository[AccountLedger]):
    model = AccountLedger

    async def get_ledger(
        self,
        company_id: UUID,
        account_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Pagination:
        stmt = (
            select(AccountLedger)
            .join(JournalVoucher, JournalVoucher.id == AccountLedger.jv_id)
            .where(
                AccountLedger.company_id == company_id,
                AccountLedger.account_id == account_id,
            )
            .order_by(AccountLedger.txn_date.asc(), JournalVoucher.created_at.asc())
        )
        if from_date:
            stmt = stmt.where(AccountLedger.txn_date >= from_date)
        if to_date:
            stmt = stmt.where(AccountLedger.txn_date <= to_date)
        return await self.paginate(stmt, page, page_size)

    async def get_cashbook(
        self,
        company_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Pagination:
        """All cash account entries."""
        cash_accts = select(Account.id).where(
            Account.company_id == company_id, Account.account_type == "cash"
        )
        stmt = (
            select(AccountLedger)
            .join(JournalVoucher, JournalVoucher.id == AccountLedger.jv_id)
            .where(
                AccountLedger.company_id == company_id,
                AccountLedger.account_id.in_(cash_accts),
            )
            .order_by(AccountLedger.txn_date.asc(), JournalVoucher.created_at.asc())
        )
        if from_date:
            stmt = stmt.where(AccountLedger.txn_date >= from_date)
        if to_date:
            stmt = stmt.where(AccountLedger.txn_date <= to_date)
        return await self.paginate(stmt, page, page_size)

    async def get_bankbook(
        self,
        company_id: UUID,
        account_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Pagination:
        bank_accts = select(Account.id).where(
            Account.company_id == company_id, Account.account_type == "bank"
        )
        stmt = (
            select(AccountLedger)
            .join(JournalVoucher, JournalVoucher.id == AccountLedger.jv_id)
            .where(
                AccountLedger.company_id == company_id,
                AccountLedger.account_id.in_(bank_accts) if not account_id
                else AccountLedger.account_id == account_id,
            )
            .order_by(AccountLedger.txn_date.asc(), JournalVoucher.created_at.asc())
        )
        if from_date:
            stmt = stmt.where(AccountLedger.txn_date >= from_date)
        if to_date:
            stmt = stmt.where(AccountLedger.txn_date <= to_date)
        return await self.paginate(stmt, page, page_size)

    async def rebuild_running_balance(self, company_id: UUID, account_id: UUID) -> None:
        """Recalculate running_balance for all ledger entries of an account."""
        stmt = text("""
            WITH ordered AS (
                SELECT id,
                       debit_amount - credit_amount AS net,
                       ROW_NUMBER() OVER (
                           PARTITION BY account_id
                           ORDER BY txn_date, id
                       ) AS rn
                FROM account_ledger
                WHERE company_id = :cid AND account_id = :aid
            ),
            cumulative AS (
                SELECT id, SUM(net) OVER (ORDER BY rn ROWS UNBOUNDED PRECEDING) AS rb
                FROM ordered
            )
            UPDATE account_ledger al
            SET running_balance = c.rb,
                balance_type = CASE WHEN c.rb >= 0 THEN 'Dr' ELSE 'Cr' END
            FROM cumulative c
            WHERE al.id = c.id
        """)
        await self.session.execute(stmt, {"cid": str(company_id), "aid": str(account_id)})


# ── GST Returns ───────────────────────────────────────────────────────────────

class GSTReturnRepository(BaseRepository[GSTReturn]):
    model = GSTReturn

    async def get_by_period(
        self, company_id: UUID, return_type: str, period_from: date
    ) -> GSTReturn | None:
        return await self.get_by(
            company_id=company_id, return_type=return_type, period_from=period_from
        )

    async def list_by_company(self, company_id: UUID, fy: str | None = None) -> list[GSTReturn]:
        stmt = (
            select(GSTReturn)
            .where(GSTReturn.company_id == company_id)
            .order_by(GSTReturn.period_from.desc())
        )
        if fy:
            stmt = stmt.where(GSTReturn.financial_year == fy)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── ITC Ledger ────────────────────────────────────────────────────────────────

class ITCLedgerRepository(BaseRepository[ITCLedger]):
    model = ITCLedger

    async def get_or_create_period(self, company_id: UUID, period: date) -> ITCLedger:
        existing = await self.get_by(company_id=company_id, period=period)
        if existing:
            return existing
        return await self.create({"company_id": company_id, "period": period})


# ── Cost Centers ──────────────────────────────────────────────────────────────

class CostCenterRepository(BaseRepository[CostCenter]):
    model = CostCenter

    async def list_active(self, company_id: UUID) -> list[CostCenter]:
        stmt = (
            select(CostCenter)
            .where(CostCenter.company_id == company_id, CostCenter.is_active == True)
            .order_by(CostCenter.cc_name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── Financial Year ────────────────────────────────────────────────────────────

class FinancialYearRepository(BaseRepository[FinancialYear]):
    model = FinancialYear

    async def get_current(self, company_id: UUID) -> FinancialYear | None:
        return await self.get_by(company_id=company_id, is_current=True)

    async def list_by_company(self, company_id: UUID) -> list[FinancialYear]:
        stmt = (
            select(FinancialYear)
            .where(FinancialYear.company_id == company_id)
            .order_by(FinancialYear.start_date.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
