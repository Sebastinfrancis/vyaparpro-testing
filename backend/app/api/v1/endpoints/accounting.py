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

from app.api.v1.dependencies import CurrentUserDep, DBDep, PaginationDep
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.schemas.accounting import (
    LedgerOut,AccountCreate, AccountGroupCreate, AccountGroupUpdate, AccountGroupOut,
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

@router.get("/groups", summary="Get full account group tree")
async def get_account_groups(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = AccountGroupService(db)
    groups = await svc.get_tree(current.company_id)
    return ok([AccountGroupOut.model_validate(g).model_dump(mode='json') for g in groups])


@router.post("/groups", status_code=201, summary="Create a custom account group")
async def create_account_group(payload: AccountGroupCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = AccountGroupService(db)
    group = await svc.create(current.company_id, payload, current.user_id)
    return created(AccountGroupOut.model_validate(group).model_dump(mode='json'), "Account group created.")


@router.patch("/groups/{group_id}", summary="Update an account group (non-system only)")
async def update_account_group(group_id: UUID, payload: AccountGroupUpdate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = AccountGroupService(db)
    group = await svc.update(group_id, payload, current.company_id)
    return ok(AccountGroupOut.model_validate(group).model_dump(mode='json'), "Account group updated.")


# ════════════════════════════════════════════════════════════════════
# SEEDING
# ════════════════════════════════════════════════════════════════════

@router.post("/seed", summary="Seed the standard chart of accounts (safe to call more than once)")
async def seed_chart_of_accounts(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    await svc.seed_default_accounts(current.company_id, current.user_id)
    return ok(message="Standard chart of accounts seeded.")


# ════════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS
# ════════════════════════════════════════════════════════════════════

@router.get("/accounts", summary="Search / filter accounts with pagination")
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


@router.post("/accounts", status_code=201, summary="Create an account")
async def create_account(payload: AccountCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    account = await svc.create(current.company_id, payload, current.user_id)
    return created(AccountOut.model_validate(account).model_dump(mode='json'), "Account created.")

@router.get("/accounts/{account_id}/ledger", summary="Per-account ledger — opening/closing balance + entries")
async def get_account_ledger(
    account_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
    pg: PaginationDep,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    ledger = await svc.get_ledger(
        account_id, current.company_id,
        date_cls.fromisoformat(from_date) if from_date else None,
        date_cls.fromisoformat(to_date) if to_date else None,
        pg.page, pg.page_size,
    )
    return ok(ledger.model_dump(mode='json'))


@router.get("/accounts/{account_id}", summary="Get one account with its current balance")
async def get_account(account_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    account = await svc.get_with_balance(account_id, current.company_id)
    return ok(AccountOut.model_validate(account).model_dump(mode='json'))


@router.patch("/accounts/{account_id}", summary="Update an account")
async def update_account(account_id: UUID, payload: AccountUpdate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = ChartOfAccountsService(db)
    account = await svc.update(account_id, payload, current.company_id)
    return ok(AccountOut.model_validate(account).model_dump(mode='json'), "Account updated.")


# ════════════════════════════════════════════════════════════════════
# JOURNAL VOUCHERS
# ════════════════════════════════════════════════════════════════════

@router.get("/vouchers", summary="Search / filter journal vouchers with pagination")
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


@router.post("/vouchers", status_code=201, summary="Create a manual journal voucher (draft, unposted)")
async def create_voucher(payload: JournalVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Journal voucher created.")


@router.post("/vouchers/quick/payment", status_code=201, summary="Quick Payment voucher (auto-posted)")
async def create_payment_voucher(payload: PaymentVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create_payment(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Payment recorded.")


@router.post("/vouchers/quick/receipt", status_code=201, summary="Quick Receipt voucher (auto-posted)")
async def create_receipt_voucher(payload: ReceiptVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create_receipt(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Receipt recorded.")


@router.post("/vouchers/quick/contra", status_code=201, summary="Quick Contra voucher (auto-posted)")
async def create_contra_voucher(payload: ContraVoucherCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.create_contra(current.company_id, payload, current.user_id)
    return created(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Contra entry recorded.")


@router.get("/vouchers/{jv_id}", summary="Get one journal voucher with its entries")
async def get_voucher(jv_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.jv_repo.get_with_entries(jv_id)
    if not jv:
        raise NotFoundError("Journal voucher not found.")
    if jv.company_id != current.company_id:
        raise PermissionDeniedError()
    return ok(JournalVoucherOut.model_validate(jv).model_dump(mode='json'))


@router.post("/vouchers/{jv_id}/post", summary="Post a voucher — writes running-balance ledger rows")
async def post_voucher(jv_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.post(jv_id, current.company_id, current.user_id)
    return ok(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Voucher posted.")


@router.post("/vouchers/{jv_id}/reverse", summary="Reverse a posted voucher with a mirror-image entry")
async def reverse_voucher(jv_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = JournalVoucherService(db)
    jv = await svc.reverse(jv_id, current.company_id, current.user_id)
    return ok(JournalVoucherOut.model_validate(jv).model_dump(mode='json'), "Reversal voucher posted.")



@router.get("/reports/cashbook", summary="All cash-account entries across the company")
async def get_cashbook(
    current: CurrentUserDep, db: DBDep, pg: PaginationDep,
    from_date: str | None = Query(None), to_date: str | None = Query(None),
) -> ORJSONResponse:
    from app.db.repositories.accounting import AccountLedgerRepository
    from app.schemas.accounting import LedgerEntryOut
    repo = AccountLedgerRepository(db)
    result = await repo.get_cashbook(
        current.company_id,
        date_cls.fromisoformat(from_date) if from_date else None,
        date_cls.fromisoformat(to_date) if to_date else None,
        pg.page, pg.page_size,
    )
    items = await _enrich_with_account_names(db, result.items)
    return paginated(items, result.total, result.page, result.page_size, result.pages)


@router.get("/reports/bankbook", summary="Bank-account entries, optionally filtered to one account")
async def get_bankbook(
    current: CurrentUserDep, db: DBDep, pg: PaginationDep,
    account_id: UUID | None = Query(None),
    from_date: str | None = Query(None), to_date: str | None = Query(None),
) -> ORJSONResponse:
    from app.db.repositories.accounting import AccountLedgerRepository
    repo = AccountLedgerRepository(db)
    result = await repo.get_bankbook(
        current.company_id, account_id,
        date_cls.fromisoformat(from_date) if from_date else None,
        date_cls.fromisoformat(to_date) if to_date else None,
        pg.page, pg.page_size,
    )
    items = await _enrich_with_account_names(db, result.items)
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




@router.get("/reports/trial-balance", summary="Trial Balance for a date range")
async def get_trial_balance(
    current: CurrentUserDep, db: DBDep,
    from_date: str = Query(...), to_date: str = Query(...),
) -> ORJSONResponse:
    svc = AccountingReportService(db)
    result = await svc.trial_balance(
        current.company_id, date_cls.fromisoformat(from_date), date_cls.fromisoformat(to_date)
    )
    return ok(result.model_dump(mode='json'))


@router.get("/reports/profit-and-loss", summary="Profit & Loss for a date range")
async def get_profit_and_loss(
    current: CurrentUserDep, db: DBDep,
    from_date: str = Query(...), to_date: str = Query(...),
) -> ORJSONResponse:
    svc = AccountingReportService(db)
    result = await svc.profit_and_loss(
        current.company_id, date_cls.fromisoformat(from_date), date_cls.fromisoformat(to_date)
    )
    return ok(result.model_dump(mode='json'))


@router.get("/reports/balance-sheet", summary="Balance Sheet as of a given date")
async def get_balance_sheet(
    current: CurrentUserDep, db: DBDep,
    as_of_date: str = Query(...),
) -> ORJSONResponse:
    svc = AccountingReportService(db)
    result = await svc.balance_sheet(current.company_id, date_cls.fromisoformat(as_of_date))
    return ok(result.model_dump(mode='json'))