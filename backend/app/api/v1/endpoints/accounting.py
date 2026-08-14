"""
Accounting / Ledger & Books API

Mounted at:  {prefix}/accounting   (see app/main.py)

── Account Groups ──────────────────────────────────────────
GET    /accounting/groups              — full group tree
POST   /accounting/groups              — create a custom group
PATCH  /accounting/groups/{id}         — update a group (non-system only)

── Seeding ──────────────────────────────────────────────────
POST   /accounting/seed                — seed the standard chart of accounts (idempotent)

── Chart of Accounts ───────────────────────────────────────
GET    /accounting/accounts            — search/filter/paginate accounts
POST   /accounting/accounts            — create an account
GET    /accounting/accounts/{id}       — get one account with its current balance
PATCH  /accounting/accounts/{id}       — update an account

── Journal Vouchers ─────────────────────────────────────────
GET    /accounting/vouchers                — search/filter/paginate
POST   /accounting/vouchers                — create a manual JV (draft, unposted)
GET    /accounting/vouchers/{id}           — get one voucher with its entries
POST   /accounting/vouchers/{id}/post      — post a voucher (writes to the ledger)
POST   /accounting/vouchers/{id}/reverse   — create + post a mirror-image reversal

── Quick vouchers (create + auto-post in one call) ─────────
POST   /accounting/vouchers/quick/payment
POST   /accounting/vouchers/quick/receipt
POST   /accounting/vouchers/quick/contra
"""
from __future__ import annotations

from datetime import date as date_cls
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse

from fastapi import Response

from app.api.v1.dependencies import CurrentUserDep, DBDep, PaginationDep, require_perm
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.utils.accounting_report_export import (
    build_balance_sheet_tables, build_ledger_like_tables, build_pl_tables,
    build_trial_balance_tables, export_response, get_company_dict,
)
from app.schemas.accounting import (
    CapitalVoucherCreate, LedgerOut,AccountCreate, AccountGroupCreate, AccountGroupUpdate, AccountGroupOut,
    AccountOut, AccountUpdate, ContraVoucherCreate, JournalVoucherCreate,
    JournalVoucherOut, PaymentVoucherCreate, ReceiptVoucherCreate,
)
from app.services.accounting import AccountGroupService, ChartOfAccountsService, JournalVoucherService
from app.utils.responses import created, ok, paginated

from app.schemas.accounting import (
    AccountCreate, AccountGroupCreate, AccountGroupUpdate, AccountGroupOut,
    AccountOut, AccountUpdate, BalanceSheetOut, ContraVoucherCreate,
    JournalVoucherCreate, JournalVoucherOut, LedgerOut, PaymentVoucherCreate,
    ProfitLossOut, ReceiptVoucherCreate, TrialBalanceOut,
)
from app.services.accounting import (
    AccountGroupService, AccountingReportService, ChartOfAccountsService, JournalVoucherService,
)

router = APIRouter()


# ════════════════════════════════════════════════════════════════════
# ACCOUNT GROUPS
# ════════════════════════════════════════════════════════════════════

@router.get("/groups", summary="Get full account group tree", dependencies=[require_perm("accounting.read")])
async def get_account_groups(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = AccountGroupService(db)
    groups = await svc.get_tree(current.company_id)
    return ok([AccountGroupOut.model_validate(g).model_dump(mode='json') for g in groups])


@router.post("/groups", status_code=201, summary="Create a custom account group", dependencies=[require_perm("accounting.create")])
async def create_account_group(payload: AccountGroupCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = AccountGroupService(db)
    group = await svc.create(current.company_id, payload, current.user_id)
    return created(AccountGroupOut.model_validate(group).model_dump(mode='json'), "Account group created.")


@router.patch("/groups/{group_id}", summary="Update an account group (non-system only)", dependencies=[require_perm("accounting.update")])
async def update_account_group(group_id: UUID, payload: AccountGroupUpdate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = AccountGroupService(db)
    group = await svc.update(group_id, payload, current.company_id)
    return ok(AccountGroupOut.model_validate(group).model_dump(mode='json'), "Account group updated.")


# ════════════════════════════════════════════════════════════════════
# SEEDING
# ════════════════════════════════════════════════════════════════════

@router.post("/seed", summary="Seed the standard chart of accounts (safe to call more than once)", dependencies=[require_perm("accounting.create")])
async def seed_chart_of_accounts(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    await svc.seed_default_accounts(current.company_id, current.user_id)
    return ok(message="Standard chart of accounts seeded.")


# ════════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS
# ════════════════════════════════════════════════════════════════════

@router.get("/accounts", summary="Search / filter accounts with pagination", dependencies=[require_perm("accounting.read")])
async def list_accounts(
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    q: str | None = Query(None, description="Search by account name or code"),
    account_type: str | None = Query(None),
    group_id: UUID | None = Query(None),
) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    result = await svc.search(
        company_id=current.company_id,
        query=q, account_type=account_type, group_id=group_id,
        page=pg.page, page_size=pg.page_size,
    )
    items = [AccountOut.model_validate(a).model_dump(mode='json') for a in result.items]
    return paginated(items, result.total, result.page, result.page_size, result.pages)


@router.post("/accounts", status_code=201, summary="Create an account", dependencies=[require_perm("accounting.create")])
async def create_account(payload: AccountCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    account = await svc.create(current.company_id, payload, current.user_id)
    return created(AccountOut.model_validate(account).model_dump(mode='json'), "Account created.")

@router.get("/accounts/{account_id}/ledger", response_model=None, summary="Per-account ledger — opening/closing balance + entries", dependencies=[require_perm("accounting.read")])
async def get_account_ledger(
    account_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    format: str = Query("json", pattern="^(json|pdf|xlsx)$"),
) -> ORJSONResponse | Response:
    svc = ChartOfAccountsService(db)
    ledger = await svc.get_ledger(
        account_id, current.company_id,
        date_cls.fromisoformat(from_date) if from_date else None,
        date_cls.fromisoformat(to_date) if to_date else None,
        pg.page, pg.page_size,
    )
    if format in ("pdf", "xlsx"):
        entries = [e.model_dump(mode="json") for e in ledger.entries]
        summary, tables = build_ledger_like_tables(
            f"Ledger — {ledger.account_code} {ledger.account_name}",
            entries, ledger.opening_balance, ledger.opening_balance_type,
            ledger.closing_balance, ledger.closing_balance_type,
        )
        company = await get_company_dict(db, current.company_id)
        period = f"{from_date or 'Beginning'} to {to_date or 'Today'}"
        return export_response(
            format, f"ledger_{ledger.account_code}_{from_date or ''}_{to_date or ''}",
            f"Ledger — {ledger.account_code} {ledger.account_name}", period,
            summary, tables, company, period,
            getattr(current, "full_name", "System"),
        )
    return ok(ledger.model_dump(mode='json'))


@router.get("/accounts/{account_id}", summary="Get one account with its current balance", dependencies=[require_perm("accounting.read")])
async def get_account(account_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    account = await svc.get_with_balance(account_id, current.company_id)
    return ok(AccountOut.model_validate(account).model_dump(mode='json'))


@router.patch("/accounts/{account_id}", summary="Update an account", dependencies=[require_perm("accounting.update")])
async def update_account(account_id: UUID, payload: AccountUpdate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    account = await svc.update(account_id, payload, current.company_id)
    return ok(AccountOut.model_validate(account).model_dump(mode='json'), "Account updated.")


# ════════════════════════════════════════════════════════════════════
# JOURNAL VOUCHERS
# ════════════════════════════════════════════════════════════════════

@router.get("/vouchers", summary="Search / filter journal vouchers with pagination", dependencies=[require_perm("accounting.read")])
async def list_vouchers(
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    jv_type: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    ref_no: str | None = Query(None),
    is_posted: bool | None = Query(None),
) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    result = await svc.jv_repo.search(
        company_id=current.company_id,
        jv_type=jv_type,
        from_date=date_cls.fromisoformat(from_date) if from_date else None,
        to_date=date_cls.fromisoformat(to_date) if to_date else None,
        ref_no=ref_no,
        is_posted=is_posted,
        page=pg.page, page_size=pg.page_size,
    )
    items = [JournalVoucherOut.model_validate(v).model_dump(mode='json') for v in result.items]
    return paginated(items, result.total, result.page, result.page_size, result.pages)


@router.post("/vouchers", status_code=201, summary="Create a manual journal voucher (draft, unposted)", dependencies=[require_perm("accounting.create")])
async def create_voucher(payload: JournalVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Journal voucher created.")


@router.post("/vouchers/quick/payment", status_code=201, summary="Quick Payment voucher (auto-posted)", dependencies=[require_perm("accounting.create")])
async def create_payment_voucher(payload: PaymentVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create_payment(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Payment recorded.")


@router.post("/vouchers/quick/receipt", status_code=201, summary="Quick Receipt voucher (auto-posted)", dependencies=[require_perm("accounting.create")])
async def create_receipt_voucher(payload: ReceiptVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create_receipt(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Receipt recorded.")


@router.post("/vouchers/quick/contra", status_code=201, summary="Quick Contra voucher (auto-posted)", dependencies=[require_perm("accounting.create")])
async def create_contra_voucher(payload: ContraVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create_contra(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Contra entry recorded.")


@router.post("/vouchers/quick/capital", status_code=201, summary="Quick Capital transaction (auto-posted)", dependencies=[require_perm("accounting.create")])
async def create_capital_voucher(payload: CapitalVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create_capital_transaction(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Capital transaction recorded.")


@router.get("/vouchers/{jv_id}", summary="Get one journal voucher with its entries", dependencies=[require_perm("accounting.read")])
async def get_voucher(jv_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.jv_repo.get_with_entries(jv_id)
    if not jv:
        raise NotFoundError("Journal voucher not found.")
    if jv.company_id != current.company_id:
        raise PermissionDeniedError()
    return ok(JournalVoucherOut.model_validate(jv).model_dump(mode='json'))


@router.post("/vouchers/{jv_id}/post", summary="Post a voucher — writes running-balance ledger rows", dependencies=[require_perm("accounting.post")])
async def post_voucher(jv_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.post(jv_id, current.company_id, current.user_id)
    return ok(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Voucher posted.")


@router.post("/vouchers/{jv_id}/reverse", summary="Reverse a posted voucher with a mirror-image entry", dependencies=[require_perm("accounting.reverse")])
async def reverse_voucher(jv_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.reverse(jv_id, current.company_id, current.user_id)
    return ok(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Reversal voucher posted.")



@router.get("/reports/cashbook", response_model=None, summary="All cash-account entries across the company", dependencies=[require_perm("accounting.read")])
async def get_cashbook(
    current: CurrentUserDep, db: DBDep, pg: PaginationDep,
    from_date: str | None = Query(None), to_date: str | None = Query(None),
    format: str = Query("json", pattern="^(json|pdf|xlsx)$"),
) -> ORJSONResponse | Response:
    from app.db.repositories.accounting import AccountLedgerRepository
    from app.schemas.accounting import LedgerEntryOut
    repo = AccountLedgerRepository(db)
    page_size = 5000 if format in ("pdf", "xlsx") else pg.page_size
    result = await repo.get_cashbook(
        current.company_id,
        date_cls.fromisoformat(from_date) if from_date else None,
        date_cls.fromisoformat(to_date) if to_date else None,
        pg.page, page_size,
    )
    items = await _enrich_with_account_names(db, result.items)
    if format in ("pdf", "xlsx"):
        opening = sum((i["debit_amount"] - i["credit_amount"]) for i in []) or 0  # cashbook has no single opening
        summary, tables = build_ledger_like_tables(
            "Cash Book", items, 0, "Dr",
            items[-1]["running_balance"] if items else 0,
            items[-1]["balance_type"] if items else "Dr",
            include_account_col=True,
        )
        company = await get_company_dict(db, current.company_id)
        period = f"{from_date or 'Beginning'} to {to_date or 'Today'}"
        return export_response(format, f"cashbook_{from_date or ''}_{to_date or ''}",
                                "Cash Book", period, summary, tables, company, period,
                                getattr(current, "full_name", "System"))
    return paginated(items, result.total, result.page, result.page_size, result.pages)


@router.get("/reports/bankbook", response_model=None, summary="Bank-account entries, optionally filtered to one account", dependencies=[require_perm("accounting.read")])
async def get_bankbook(
    current: CurrentUserDep, db: DBDep, pg: PaginationDep,
    account_id: UUID | None = Query(None),
    from_date: str | None = Query(None), to_date: str | None = Query(None),
    format: str = Query("json", pattern="^(json|pdf|xlsx)$"),
) -> ORJSONResponse | Response:
    from app.db.repositories.accounting import AccountLedgerRepository
    repo = AccountLedgerRepository(db)
    page_size = 5000 if format in ("pdf", "xlsx") else pg.page_size
    result = await repo.get_bankbook(
        current.company_id, account_id,
        date_cls.fromisoformat(from_date) if from_date else None,
        date_cls.fromisoformat(to_date) if to_date else None,
        pg.page, page_size,
    )
    items = await _enrich_with_account_names(db, result.items)
    if format in ("pdf", "xlsx"):
        summary, tables = build_ledger_like_tables(
            "Bank Book", items, 0, "Dr",
            items[-1]["running_balance"] if items else 0,
            items[-1]["balance_type"] if items else "Dr",
            include_account_col=True,
        )
        company = await get_company_dict(db, current.company_id)
        period = f"{from_date or 'Beginning'} to {to_date or 'Today'}"
        return export_response(format, f"bankbook_{from_date or ''}_{to_date or ''}",
                                "Bank Book", period, summary, tables, company, period,
                                getattr(current, "full_name", "System"))
    return paginated(items, result.total, result.page, result.page_size, result.pages)


async def _enrich_with_account_names(db, entries) -> list[dict]:
    """Attach account_name to each ledger entry dict — one batch lookup, not N+1 queries."""
    from app.schemas.accounting import LedgerEntryOut
    from app.db.models.accounting import Account
    from sqlalchemy import select

    acct_ids = {e.account_id for e in entries}
    names: dict = {}
    if acct_ids:
        rows = (await db.execute(
            select(Account.id, Account.account_name).where(Account.id.in_(acct_ids))
        )).all()
        names = {row[0]: row[1] for row in rows}

    out = []
    for e in entries:
        d = LedgerEntryOut.model_validate(e).model_dump(mode='json')
        d["account_name"] = names.get(e.account_id, "")
        out.append(d)
    return out




@router.get("/reports/trial-balance", response_model=None, summary="Trial Balance for a date range", dependencies=[require_perm("accounting.read")])
async def get_trial_balance(
    current: CurrentUserDep, db: DBDep,
    from_date: str = Query(...), to_date: str = Query(...),
    format: str = Query("json", pattern="^(json|pdf|xlsx)$"),
) -> ORJSONResponse | Response:
    svc = AccountingReportService(db)
    result = await svc.trial_balance(
        current.company_id, date_cls.fromisoformat(from_date), date_cls.fromisoformat(to_date)
    )
    if format in ("pdf", "xlsx"):
        summary, tables = build_trial_balance_tables(result)
        company = await get_company_dict(db, current.company_id)
        period = f"{from_date} to {to_date}"
        return export_response(format, f"trial_balance_{from_date}_{to_date}",
                                "Trial Balance", period, summary, tables, company, period,
                                getattr(current, "full_name", "System"))
    return ok(result.model_dump(mode='json'))


@router.get("/reports/profit-and-loss", response_model=None, summary="Profit & Loss for a date range", dependencies=[require_perm("accounting.read")])
async def get_profit_and_loss(
    current: CurrentUserDep, db: DBDep,
    from_date: str = Query(...), to_date: str = Query(...),
    format: str = Query("json", pattern="^(json|pdf|xlsx)$"),
) -> ORJSONResponse | Response:
    svc = AccountingReportService(db)
    result = await svc.profit_and_loss(
        current.company_id, date_cls.fromisoformat(from_date), date_cls.fromisoformat(to_date)
    )
    if format in ("pdf", "xlsx"):
        summary, tables = build_pl_tables(result)
        company = await get_company_dict(db, current.company_id)
        period = f"{from_date} to {to_date}"
        return export_response(format, f"profit_and_loss_{from_date}_{to_date}",
                                "Profit & Loss Statement", period, summary, tables, company, period,
                                getattr(current, "full_name", "System"))
    return ok(result.model_dump(mode='json'))


@router.get("/reports/balance-sheet", response_model=None, summary="Balance Sheet as of a given date", dependencies=[require_perm("accounting.read")])
async def get_balance_sheet(
    current: CurrentUserDep, db: DBDep,
    as_of_date: str = Query(...),
    format: str = Query("json", pattern="^(json|pdf|xlsx)$"),
) -> ORJSONResponse | Response:
    svc = AccountingReportService(db)
    result = await svc.balance_sheet(current.company_id, date_cls.fromisoformat(as_of_date))
    if format in ("pdf", "xlsx"):
        summary, tables = build_balance_sheet_tables(result)
        company = await get_company_dict(db, current.company_id)
        period = f"As of {as_of_date}"
        return export_response(format, f"balance_sheet_{as_of_date}",
                                "Balance Sheet", period, summary, tables, company, period,
                                getattr(current, "full_name", "System"))
    return ok(result.model_dump(mode='json'))