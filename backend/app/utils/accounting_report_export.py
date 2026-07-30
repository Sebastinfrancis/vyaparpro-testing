"""
VyaparPro — Accounting Report Export Helpers
Converts AccountingReportService results (Trial Balance, P&L, Balance Sheet)
and ledger/cashbook/bankbook rows into the (title, subtitle, summary, tables)
shape consumed by both generate_report_pdf() and generate_report_xlsx().
"""
from __future__ import annotations

from fastapi import Response
from sqlalchemy import text

from app.utils.excel_generator import generate_report_xlsx
from app.utils.pdf_generator import format_inr, generate_report_pdf


async def get_company_dict(db, company_id) -> dict:
    row = (await db.execute(
        text("SELECT legal_name, reg_address, gstin, phone, email, website FROM companies WHERE id = :cid"),
        {"cid": str(company_id)},
    )).mappings().one_or_none()
    return dict(row) if row else {}


def export_response(fmt: str, filename_base: str, title: str, subtitle: str,
                     summary: list, tables: list, company: dict, period: str,
                     generated_by: str) -> Response:
    """fmt is 'pdf' or 'xlsx'. Returns a ready-to-return FastAPI Response."""
    if fmt == "xlsx":
        data = generate_report_xlsx(title, subtitle, summary, tables, company=company, period=period)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    else:
        data = generate_report_pdf(title, subtitle, summary, tables, company=company,
                                    period=period, generated_by=generated_by)
        media_type = "application/pdf"
        ext = "pdf"
    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.{ext}"'},
    )


# ── Trial Balance ──────────────────────────────────────────────────────
def build_trial_balance_tables(result) -> tuple[list, list]:
    headers = ["Code", "Account", "Group", "Opening Dr", "Opening Cr",
               "Period Dr", "Period Cr", "Closing Dr", "Closing Cr"]
    rows = [
        [r.account_code, r.account_name, r.group_name,
         format_inr(r.opening_dr), format_inr(r.opening_cr),
         format_inr(r.period_dr), format_inr(r.period_cr),
         format_inr(r.closing_dr), format_inr(r.closing_cr)]
        for r in result.rows
    ]
    rows.append(["", "", "TOTAL", "", "", "", "", format_inr(result.total_dr), format_inr(result.total_cr)])
    summary = [
        ("Total Debit", format_inr(result.total_dr), "blue"),
        ("Total Credit", format_inr(result.total_cr), "green"),
        ("Status", "Balanced" if result.is_balanced else "Out of Balance",
         "green" if result.is_balanced else "red"),
    ]
    return summary, [("Trial Balance", headers, rows)]


# ── Profit & Loss ───────────────────────────────────────────────────────
def _flatten_pl_rows(rows, indent: int = 0) -> list:
    out = []
    for r in rows:
        prefix = "    " * indent
        label = prefix + (r.label.upper() if r.is_heading and indent == 0 else r.label)
        amount = "" if (r.is_heading and r.children) else format_inr(r.amount)
        out.append([label, amount])
        if r.children:
            out.extend(_flatten_pl_rows(r.children, indent + 1))
    return out


def build_pl_tables(result) -> tuple[list, list]:
    headers = ["Particulars", "Amount"]
    rows = _flatten_pl_rows(result.rows)
    summary = [
        ("Gross Profit", format_inr(result.gross_profit), "blue"),
        ("Operating Profit", format_inr(result.operating_profit), "orange"),
        ("Net Profit", format_inr(result.net_profit),
         "green" if result.net_profit >= 0 else "red"),
    ]
    return summary, [("Profit & Loss Statement", headers, rows)]


# ── Balance Sheet ───────────────────────────────────────────────────────
def _flatten_bs_rows(rows, indent: int = 0) -> list:
    out = []
    for r in rows:
        prefix = "    " * indent
        label = prefix + (r.label.upper() if r.is_heading and indent == 0 else r.label)
        amount = "" if (r.is_heading and r.children) else format_inr(r.amount)
        out.append([label, amount])
        if r.children:
            out.extend(_flatten_bs_rows(r.children, indent + 1))
    return out


def build_balance_sheet_tables(result) -> tuple[list, list]:
    headers = ["Particulars", "Amount"]
    summary = [
        ("Total Assets", format_inr(result.total_assets), "blue"),
        ("Total Liabilities", format_inr(result.total_liabilities), "orange"),
        ("Net Worth", format_inr(result.net_worth), "green"),
    ]
    return summary, [
        ("Assets", headers, _flatten_bs_rows(result.assets)),
        ("Liabilities & Equity", headers, _flatten_bs_rows(result.liabilities)),
    ]


# ── Ledger / Cash Book / Bank Book (shared row shape) ───────────────────
def build_ledger_like_tables(section_title: str, entries: list, opening_balance,
                              opening_type: str, closing_balance, closing_type: str,
                              include_account_col: bool = False) -> tuple[list, list]:
    headers = (["Date", "Account", "Voucher", "Narration", "Debit", "Credit", "Balance"]
               if include_account_col else
               ["Date", "Voucher", "Narration", "Debit", "Credit", "Balance"])
    rows = []
    for e in entries:
        row = [str(e.get("txn_date", e.get("date", "")))]
        if include_account_col:
            row.append(e.get("account_name", ""))
        row += [
            e.get("voucher_no", e.get("jv_no", "")),
            e.get("narration", "") or "—",
            format_inr(e.get("debit_amount", 0)) if e.get("debit_amount") else "—",
            format_inr(e.get("credit_amount", 0)) if e.get("credit_amount") else "—",
            f'{format_inr(e.get("running_balance", 0))} {e.get("balance_type", "")}',
        ]
        rows.append(row)
    summary = [
        ("Opening Balance", f"{format_inr(opening_balance)} {opening_type}", "blue"),
        ("Closing Balance", f"{format_inr(closing_balance)} {closing_type}", "green"),
    ]
    return summary, [(section_title, headers, rows)]