"""
app/ai_assistant/data_queries.py
──────────────────────────────────────────────────────────────────────────
"Database question" handlers for the AI Assistant.

These are intentionally small, read-only, company-scoped queries — the
same style already used in app/api/v1/endpoints/reports.py (raw SQL via
the existing async SQLAlchemy session, filtered by company_id). No new
tables, no new services, no writes.

Each function:
  * takes the existing request-scoped `AsyncSession` (db) and the caller's
    `company_id` (from CurrentUser — never trusts client-supplied IDs),
  * fetches only the minimum data needed,
  * returns a ready-to-display natural-language sentence.

The function name here must match the `"handler"` value for the
corresponding entry in `knowledge_base.DATA_KB`.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.pdf_generator import format_inr
from app.db.sql_compat import month_start_sql

_ACTIVE_INVOICE = "status NOT IN ('draft','cancelled','void') AND invoice_type != 'credit_note'"


async def today_sales(db: AsyncSession, company_id: UUID) -> str:
    row = (await db.execute(text(f"""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount), 0) AS total
        FROM invoices
        WHERE company_id = :cid AND invoice_date = CURRENT_DATE AND {_ACTIVE_INVOICE}
    """), {"cid": str(company_id)})).mappings().one()

    if not row["cnt"]:
        return "No sales recorded yet today."
    return f"Today you've billed **{row['cnt']}** invoice(s) totaling **{format_inr(row['total'])}**."


async def month_sales(db: AsyncSession, company_id: UUID) -> str:
    row = (await db.execute(text(f"""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount), 0) AS total
        FROM invoices
        WHERE company_id = :cid
          AND invoice_date >= {month_start_sql()}
          AND {_ACTIVE_INVOICE}
    """), {"cid": str(company_id)})).mappings().one()

    if not row["cnt"]:
        return "No sales recorded yet this month."
    return f"This month you've billed **{row['cnt']}** invoice(s) totaling **{format_inr(row['total'])}**."


async def low_stock(db: AsyncSession, company_id: UUID) -> str:
    rows = (await db.execute(text("""
        SELECT product_name, current_stock, reorder_level
        FROM products
        WHERE company_id = :cid AND track_inventory = TRUE
          AND is_active = TRUE AND current_stock <= reorder_level
        ORDER BY current_stock ASC
        LIMIT 5
    """), {"cid": str(company_id)})).mappings().all()

    if not rows:
        return "Nothing is low on stock right now — all tracked products are above their reorder level. ✅"

    lines = "\n".join(
        f"• **{r['product_name']}** — {r['current_stock']} left (reorder at {r['reorder_level']})"
        for r in rows
    )
    return f"These products are low on stock:\n{lines}"


async def top_customers(db: AsyncSession, company_id: UUID) -> str:
    rows = (await db.execute(text(f"""
        SELECT COALESCE(p.display_name, i.billing_name) AS customer_name, SUM(i.total_amount) AS total
        FROM invoices i LEFT JOIN parties p ON p.id = i.party_id
        WHERE i.company_id = :cid AND {_ACTIVE_INVOICE}
          AND i.invoice_date >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY p.display_name, i.billing_name
        ORDER BY total DESC
        LIMIT 5
    """), {"cid": str(company_id)})).mappings().all()

    if not rows:
        return "No invoices in the last 90 days to rank customers by."

    lines = "\n".join(f"• **{r['customer_name'] or '—'}** — {format_inr(r['total'])}" for r in rows)
    return f"Your top customers (last 90 days) by revenue:\n{lines}"


async def pending_payments(db: AsyncSession, company_id: UUID) -> str:
    row = (await db.execute(text("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount - paid_amount), 0) AS due
        FROM invoices
        WHERE company_id = :cid
          AND status NOT IN ('paid', 'cancelled', 'void', 'draft')
          AND invoice_type != 'credit_note'
    """), {"cid": str(company_id)})).mappings().one()

    if not row["cnt"]:
        return "No pending payments — every invoice is settled. ✅"
    return f"You have **{row['cnt']}** invoice(s) with payments pending, totaling **{format_inr(row['due'])}** due."


async def open_purchase_orders(db: AsyncSession, company_id: UUID) -> str:
    row = (await db.execute(text("""
        SELECT COUNT(*) AS cnt
        FROM purchase_orders
        WHERE company_id = :cid AND status NOT IN ('closed', 'cancelled')
    """), {"cid": str(company_id)})).mappings().one()

    if not row["cnt"]:
        return "You have no open purchase orders right now."
    return f"You have **{row['cnt']}** open purchase order(s) (not yet closed or cancelled)."


async def customer_count(db: AsyncSession, company_id: UUID) -> str:
    row = (await db.execute(text("""
        SELECT COUNT(*) AS cnt FROM parties
        WHERE company_id = :cid AND party_type IN ('customer', 'both')
    """), {"cid": str(company_id)})).mappings().one()

    return f"You currently have **{row['cnt']}** customer(s) on record."


async def branch_list(db: AsyncSession, company_id: UUID) -> str:
    rows = (await db.execute(text("""
        SELECT branch_name, branch_code, city, is_head_office, manager_name
        FROM branches
        WHERE company_id = :cid AND is_active = TRUE
        ORDER BY is_head_office DESC, branch_name ASC
    """), {"cid": str(company_id)})).mappings().all()

    if not rows:
        return "No branches set up yet — you can add one under **Branches**."

    lines = []
    for r in rows:
        tag = " 🏢 Head Office" if r["is_head_office"] else ""
        loc = f", {r['city']}" if r["city"] else ""
        mgr = f" — Manager: {r['manager_name']}" if r["manager_name"] else ""
        lines.append(f"• **{r['branch_name']}** ({r['branch_code']}){loc}{tag}{mgr}")
    return f"You have **{len(rows)}** branch(es):\n" + "\n".join(lines)


async def branch_performance(db: AsyncSession, company_id: UUID) -> str:
    rows = (await db.execute(text(f"""
        SELECT b.branch_name,
               COUNT(i.id) AS cnt,
               COALESCE(SUM(i.total_amount), 0) AS total
        FROM branches b
        LEFT JOIN invoices i ON i.branch_id = b.id AND i.company_id = b.company_id
          AND {_ACTIVE_INVOICE}
          AND i.invoice_date >= {month_start_sql()}
        WHERE b.company_id = :cid AND b.is_active = TRUE
        GROUP BY b.branch_name
        ORDER BY total DESC
    """), {"cid": str(company_id)})).mappings().all()

    if not rows:
        return "No branches set up yet — you can add one under **Branches**."

    lines = "\n".join(
        f"• **{r['branch_name']}** — {format_inr(r['total'])} ({r['cnt']} invoice(s))"
        for r in rows
    )
    return f"This month's sales by branch:\n{lines}"


async def total_payables(db: AsyncSession, company_id: UUID) -> str:
    row = (await db.execute(text("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount - paid_amount), 0) AS due
        FROM purchase_orders
        WHERE company_id = :cid AND status NOT IN ('closed', 'cancelled')
          AND (total_amount - paid_amount) > 0
    """), {"cid": str(company_id)})).mappings().one()

    if not row["cnt"]:
        return "No payables outstanding — every vendor is settled. ✅"
    return (f"You owe **{format_inr(row['due'])}** across **{row['cnt']}** "
            f"vendor bill(s)/purchase order(s).")


async def _account_type_balance(db: AsyncSession, company_id: UUID, account_type: str, label: str) -> str:
    rows = (await db.execute(text("""
        WITH latest_ledger AS (
            SELECT DISTINCT ON (account_id) account_id, running_balance, balance_type
            FROM account_ledger
            WHERE company_id = :cid
            ORDER BY account_id, txn_date DESC, id DESC
        )
        SELECT a.account_name,
               COALESCE(l.running_balance, a.opening_balance) AS balance,
               COALESCE(l.balance_type, a.opening_balance_type) AS balance_type
        FROM accounts a
        LEFT JOIN latest_ledger l ON l.account_id = a.id
        WHERE a.company_id = :cid AND a.is_active = TRUE AND a.account_type = :atype
        ORDER BY a.account_name
    """), {"cid": str(company_id), "atype": account_type})).mappings().all()

    if not rows:
        return f"No {label} accounts are set up yet — add one under **Ledger & Books → Chart of Accounts**."

    net = sum((r["balance"] if r["balance_type"] == "Dr" else -r["balance"]) for r in rows)
    if len(rows) == 1:
        r = rows[0]
        return f"**{r['account_name']}** balance: **{format_inr(r['balance'])} {r['balance_type']}**."

    lines = "\n".join(
        f"• **{r['account_name']}** — {format_inr(r['balance'])} {r['balance_type']}"
        for r in rows
    )
    return (f"Total {label} balance: **{format_inr(abs(net))} {'Dr' if net >= 0 else 'Cr'}** "
            f"across {len(rows)} account(s):\n{lines}")


async def cash_balance(db: AsyncSession, company_id: UUID) -> str:
    return await _account_type_balance(db, company_id, "cash", "cash")


async def bank_balance(db: AsyncSession, company_id: UUID) -> str:
    return await _account_type_balance(db, company_id, "bank", "bank")


async def accounts_summary(db: AsyncSession, company_id: UUID) -> str:
    rows = (await db.execute(text("""
        SELECT g.nature, COUNT(a.id) AS cnt
        FROM accounts a
        JOIN account_groups g ON g.id = a.group_id
        WHERE a.company_id = :cid AND a.is_active = TRUE
        GROUP BY g.nature
        ORDER BY g.nature
    """), {"cid": str(company_id)})).mappings().all()

    if not rows:
        return "No accounts set up yet — check **Ledger & Books → Chart of Accounts**."

    total = sum(r["cnt"] for r in rows)
    lines = "\n".join(f"• {r['nature'].title()} — {r['cnt']}" for r in rows)
    return f"Your Chart of Accounts has **{total}** account(s):\n{lines}"


async def branch_lookup(db: AsyncSession, company_id: UUID, name: str) -> str:
    """
    Answers "branch X" / "about branch X" style questions — looks the name
    up against branches (name/code/city) and summarizes this month's sales
    and current stock position for that branch.
    """
    name = (name or "").strip()
    if not name:
        return 'Tell me a branch name to look up — e.g. "branch Chennai".'

    branch = (await db.execute(text("""
        SELECT id, branch_name, branch_code, city, gstin, manager_name,
               is_head_office, monthly_target
        FROM branches
        WHERE company_id = :cid AND is_active = TRUE
          AND (branch_name ILIKE :pat OR branch_code ILIKE :pat OR city ILIKE :pat)
        ORDER BY (LOWER(branch_name) = :exact) DESC, branch_name ASC
        LIMIT 1
    """), {"cid": str(company_id), "pat": f"%{name}%", "exact": name.lower()})).mappings().one_or_none()

    if not branch:
        return (f'I couldn\'t find a branch matching "{name}". '
                f"Check the spelling, or look under **Branches**.")

    bid = branch["id"]
    sales_row = (await db.execute(text(f"""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount), 0) AS total
        FROM invoices
        WHERE company_id = :cid AND branch_id = :bid
          AND invoice_date >= {month_start_sql()}
          AND {_ACTIVE_INVOICE}
    """), {"cid": str(company_id), "bid": str(bid)})).mappings().one()

    stock_row = (await db.execute(text("""
        SELECT COALESCE(SUM(s.quantity), 0) AS total_qty,
               COUNT(*) FILTER (WHERE p.track_inventory AND s.quantity <= p.reorder_level) AS low_cnt
        FROM inventory_stock s
        JOIN warehouses w ON w.id = s.warehouse_id
        JOIN products p ON p.id = s.product_id
        WHERE w.branch_id = :bid AND w.company_id = :cid
    """), {"cid": str(company_id), "bid": str(bid)})).mappings().one()

    tag = " 🏢 Head Office" if branch["is_head_office"] else ""
    loc = f", {branch['city']}" if branch["city"] else ""
    gst = f" GSTIN: {branch['gstin']}." if branch["gstin"] else ""
    mgr = f" Manager: {branch['manager_name']}." if branch["manager_name"] else ""
    target = (f" Monthly target: {format_inr(branch['monthly_target'])}."
              if branch["monthly_target"] else "")

    sales_line = (f"This month: **{sales_row['cnt']}** invoice(s) totaling "
                  f"**{format_inr(sales_row['total'])}**.")
    stock_line = (f" Stock on hand: **{stock_row['total_qty']}** unit(s)"
                  + (f", **{stock_row['low_cnt']}** item(s) low on stock." if stock_row["low_cnt"] else "."))

    return (f"**{branch['branch_name']}** ({branch['branch_code']}){loc}{tag}.{gst}{mgr}{target}\n"
            f"{sales_line}{stock_line}")


async def account_lookup(db: AsyncSession, company_id: UUID, name: str) -> str:
    """
    Answers "account X" / "ledger of X" / "balance of X" style questions —
    looks the name up against the Chart of Accounts and shows the current
    balance plus the last few ledger entries.
    """
    name = (name or "").strip()
    if not name:
        return 'Tell me an account name to look up — e.g. "ledger of HDFC Bank".'

    account = (await db.execute(text("""
        SELECT id, account_name, account_code, account_type, opening_balance, opening_balance_type
        FROM accounts
        WHERE company_id = :cid AND is_active = TRUE
          AND (account_name ILIKE :pat OR account_code ILIKE :pat)
        ORDER BY (LOWER(account_name) = :exact) DESC, account_name ASC
        LIMIT 1
    """), {"cid": str(company_id), "pat": f"%{name}%", "exact": name.lower()})).mappings().one_or_none()

    if not account:
        return (f'I couldn\'t find an account matching "{name}". '
                f"Check the spelling, or look under **Ledger & Books → Chart of Accounts**.")

    aid = account["id"]
    latest = (await db.execute(text("""
        SELECT running_balance, balance_type
        FROM account_ledger
        WHERE company_id = :cid AND account_id = :aid
        ORDER BY txn_date DESC, id DESC
        LIMIT 1
    """), {"cid": str(company_id), "aid": str(aid)})).mappings().one_or_none()

    if latest:
        balance, balance_type = latest["running_balance"], latest["balance_type"]
    else:
        balance, balance_type = account["opening_balance"], account["opening_balance_type"]

    recent = (await db.execute(text("""
        SELECT txn_date, jv_no, debit_amount, credit_amount, narration
        FROM account_ledger
        WHERE company_id = :cid AND account_id = :aid
        ORDER BY txn_date DESC, id DESC
        LIMIT 3
    """), {"cid": str(company_id), "aid": str(aid)})).mappings().all()

    lines = ""
    if recent:
        lines = "\nRecent entries:\n" + "\n".join(
            f"• {r['txn_date']} — {r['jv_no']}: "
            + (f"Dr {format_inr(r['debit_amount'])}" if r["debit_amount"] else f"Cr {format_inr(r['credit_amount'])}")
            + (f" ({r['narration']})" if r["narration"] else "")
            for r in recent
        )

    return (f"**{account['account_name']}** ({account['account_type']}) — "
            f"balance: **{format_inr(balance)} {balance_type}**.{lines}")


async def party_lookup(db: AsyncSession, company_id: UUID, name: str) -> str:
    """
    Answers "about <name>" / "customer <name>" / "vendor <name>" style
    questions — looks the name up against parties (customers & vendors)
    first, then CRM leads, and summarizes what's on record for them.
    """
    name = (name or "").strip()
    if not name:
        return 'Tell me a name to look up — e.g. "about Kumar Electronics".'

    party = (await db.execute(text("""
        SELECT id, display_name, party_type, gstin, phone, billing_city
        FROM parties
        WHERE company_id = :cid AND is_active = TRUE
          AND (LOWER(display_name) LIKE LOWER(:pat) OR LOWER(legal_name) LIKE LOWER(:pat))
        ORDER BY (LOWER(display_name) = :exact) DESC, display_name ASC
        LIMIT 1
    """), {"cid": str(company_id), "pat": f"%{name}%", "exact": name.lower()})).mappings().one_or_none()

    if party:
        pid = party["id"]
        if party["party_type"] == "vendor":
            row = (await db.execute(text("""
                SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount), 0) AS total,
                       COALESCE(SUM(total_amount - paid_amount)
                                FILTER (WHERE status NOT IN ('closed', 'cancelled')), 0) AS due,
                       MAX(po_date) AS last_date
                FROM purchase_orders WHERE company_id = :cid AND vendor_id = :pid
            """), {"cid": str(company_id), "pid": str(pid)})).mappings().one()
            kind = "Vendor"
            biz_line = f"You've placed **{row['cnt']}** purchase order(s) with them totaling {format_inr(row['total'])}."
            due_line = (f" **{format_inr(row['due'])}** is currently payable."
                        if row["due"] else " Nothing payable right now. ✅")
        else:
            row = (await db.execute(text("""
                SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount), 0) AS total,
                       COALESCE(SUM(total_amount - paid_amount)
                                FILTER (WHERE status NOT IN ('paid', 'cancelled', 'void', 'draft')), 0) AS due,
                       MAX(invoice_date) AS last_date
                FROM invoices
                WHERE company_id = :cid AND party_id = :pid AND invoice_type != 'credit_note'
            """), {"cid": str(company_id), "pid": str(pid)})).mappings().one()
            kind = "Customer"
            biz_line = f"They've been billed **{row['cnt']}** invoice(s) totaling {format_inr(row['total'])}."
            due_line = (f" **{format_inr(row['due'])}** is currently outstanding."
                        if row["due"] else " No outstanding dues. ✅")

        loc = f", {party['billing_city']}" if party["billing_city"] else ""
        gst = f" GSTIN: {party['gstin']}." if party["gstin"] else ""
        contact = f" 📞 {party['phone']}." if party["phone"] else ""
        last = f" Last activity: {row['last_date']}." if row["last_date"] else ""
        return f"**{party['display_name']}** ({kind}{loc}).{gst}{contact}\n{biz_line}{due_line}{last}"

    lead = (await db.execute(text("""
        SELECT lead_name, company_name, stage, value, follow_up_date
        FROM crm_leads
        WHERE company_id = :cid AND is_active = TRUE
          AND (LOWER(lead_name) LIKE LOWER(:pat) OR LOWER(company_name) LIKE LOWER(:pat))
        ORDER BY (LOWER(lead_name) = :exact) DESC
        LIMIT 1
    """), {"cid": str(company_id), "pat": f"%{name}%", "exact": name.lower()})).mappings().one_or_none()

    if lead:
        company_part = f" — {lead['company_name']}" if lead["company_name"] else ""
        fu = f" Next follow-up: {lead['follow_up_date']}." if lead["follow_up_date"] else ""
        return (f"**{lead['lead_name']}**{company_part} is a CRM lead at stage "
                f"**{lead['stage']}**, valued at {format_inr(lead['value'])}.{fu}")

    return (f'I couldn\'t find a customer, vendor or lead matching "{name}". '
            f"Check the spelling, or search directly in **Customers** / **Vendors** / **CRM**.")


# Registry consumed by responder.py — maps DATA_KB "handler" names to functions.
HANDLERS = {
    "today_sales": today_sales,
    "month_sales": month_sales,
    "low_stock": low_stock,
    "top_customers": top_customers,
    "pending_payments": pending_payments,
    "open_purchase_orders": open_purchase_orders,
    "customer_count": customer_count,
    "branch_list": branch_list,
    "branch_performance": branch_performance,
    "total_payables": total_payables,
    "cash_balance": cash_balance,
    "bank_balance": bank_balance,
    "accounts_summary": accounts_summary,
}
