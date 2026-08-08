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
          AND invoice_date >= date_trunc('month', CURRENT_DATE)::date
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
          AND (display_name ILIKE :pat OR legal_name ILIKE :pat)
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
          AND (lead_name ILIKE :pat OR company_name ILIKE :pat)
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
}
