"""VyaparPro — GST Compliance Reports (live-computed, read-only)"""
from __future__ import annotations
from datetime import date
import calendar
from app import db
from uuid import UUID
from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse
from sqlalchemy import text

from app.api.v1.dependencies import CurrentUserDep, DBDep, require_perm
from app.utils.responses import ok
from datetime import datetime as dt_now
from app.db.models.accounting import GSTReturn
from fastapi.responses import Response
from app.utils.pdf_generator import generate_report_pdf, format_inr

router = APIRouter()

# ────────────────────────────────────────────────────────────────────
# Shared SQL fragments — every GST report must use the SAME definition
# of "what counts as a supply" and "what counts as claimable ITC", or
# the different tabs/reports will disagree with each other and with
# GSTR-3B (which is the one that actually gets filed).
# ────────────────────────────────────────────────────────────────────

# Only these invoice_type values are real GST supplies. 'proforma_invoice' and
# 'delivery_challan' share the invoices table but are NOT taxable supplies and
# must never be counted in GST figures.
_GST_INVOICE_TYPES = "('tax_invoice','debit_note','credit_note')"

# Signed taxable/tax value for a document: credit notes reduce the figure,
# tax invoices and debit notes add to it. Matches the logic already used in
# /gstr3b so every report nets credit notes the same way.
def _signed(col: str, alias: str = "") -> str:
    # col may be a single column or a "+"-joined compound expression
    # (e.g. 'cgst_amount+sgst_amount+igst_amount'); wrap the WHOLE sum in
    # parens so the credit-note negation applies to every term, not just
    # the first one.
    a = f" AS {alias}" if alias else ""
    expr = "+".join(c.strip() for c in col.split("+"))
    return f"COALESCE(SUM(CASE WHEN invoice_type='credit_note' THEN -({expr}) ELSE ({expr}) END),0){a}"

def _signed_i(col: str, alias: str = "") -> str:
    """Same as _signed but for queries that alias the invoices table as 'i'.
    Every term gets the i. prefix individually (not just the first one) —
    otherwise bare column names collide with invoice_items' identically
    named cgst/sgst/igst columns and Postgres raises AmbiguousColumnError."""
    a = f" AS {alias}" if alias else ""
    expr = "+".join(f"i.{c.strip()}" for c in col.split("+"))
    return f"COALESCE(SUM(CASE WHEN i.invoice_type='credit_note' THEN -({expr}) ELSE ({expr}) END),0){a}"

# Net-of-receipt, net-of-returns ITC per PO line item. Two corrections layered:
#  1. ITC can only be claimed on goods actually RECEIVED (Sec 16(2)(b)) — a PO
#     that's merely created/sent (received_qty=0) must contribute zero ITC,
#     not the full ordered-quantity tax.
#  2. Of what was received, any quantity since returned to the vendor (Rule 37)
#     must be backed out too.
# NULLIF guards against a zero-quantity line dividing by zero.
def _signed_ii(col: str, alias: str = "") -> str:
    """For queries joining invoice_items (aliased ii) to invoices (aliased i):
    sums the LINE ITEM's column (ii.{col}) — not the invoice header's — signed
    by the PARENT invoice's type (a credit note's sign lives on the header,
    line items don't carry it themselves). Using _signed_i here by mistake
    summed the header's total once per line item instead of the item's own
    share, silently multiplying multi-item invoices' contribution."""
    a = f" AS {alias}" if alias else ""
    expr = "+".join(f"ii.{c.strip()}" for c in col.split("+"))
    return f"COALESCE(SUM(CASE WHEN i.invoice_type='credit_note' THEN -({expr}) ELSE ({expr}) END),0){a}"

_ITC_CGST = "poi.cgst_amount * (poi.received_qty - poi.returned_qty) / NULLIF(poi.quantity, 0)"
_ITC_SGST = "poi.sgst_amount * (poi.received_qty - poi.returned_qty) / NULLIF(poi.quantity, 0)"
_ITC_IGST = "poi.igst_amount * (poi.received_qty - poi.returned_qty) / NULLIF(poi.quantity, 0)"


def _month_bounds(month: str) -> tuple[date, date]:
    """month = 'YYYY-MM' -> (first_day, last_day)"""
    y, m = int(month[:4]), int(month[5:7])
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last_day)


def _clean(obj):
    from decimal import Decimal
    import uuid
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID) or type(obj).__name__ == "UUID":
        return str(obj)
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj

def _compute_setoff(outward: dict, itc: dict) -> dict:
    """
    Section 49A / 49B and Rule 88A — ITC set-off order:
      1. IGST ITC must be fully exhausted first: against IGST liability first,
         then any leftover against CGST liability, then SGST liability.
      2. CGST ITC can only be used for CGST liability first; any leftover
         can then be used against IGST liability. CGST ITC can NEVER offset SGST.
      3. SGST ITC can only be used for SGST liability first; any leftover
         can then be used against IGST liability. SGST ITC can NEVER offset CGST.
    Returns net cash payable per head plus unutilised ITC carried forward.
    """
    igst_liab = float(outward.get("igst", 0) or 0)
    cgst_liab = float(outward.get("cgst", 0) or 0)
    sgst_liab = float(outward.get("sgst", 0) or 0)

    igst_itc = float(itc.get("igst", 0) or 0)
    cgst_itc = float(itc.get("cgst", 0) or 0)
    sgst_itc = float(itc.get("sgst", 0) or 0)

    # Step 1: IGST ITC -> IGST liability first
    used = min(igst_itc, igst_liab)
    igst_liab -= used
    igst_itc -= used

    # Step 2: leftover IGST ITC -> CGST liability, then SGST liability
    used = min(igst_itc, cgst_liab)
    cgst_liab -= used
    igst_itc -= used

    used = min(igst_itc, sgst_liab)
    sgst_liab -= used
    igst_itc -= used  # remaining IGST ITC (if any) is carried forward

    # Step 3: CGST ITC -> CGST liability first
    used = min(cgst_itc, cgst_liab)
    cgst_liab -= used
    cgst_itc -= used

    # Step 4: leftover CGST ITC -> IGST liability only
    used = min(cgst_itc, igst_liab)
    igst_liab -= used
    cgst_itc -= used

    # Step 5: SGST ITC -> SGST liability first
    used = min(sgst_itc, sgst_liab)
    sgst_liab -= used
    sgst_itc -= used

    # Step 6: leftover SGST ITC -> IGST liability only
    used = min(sgst_itc, igst_liab)
    igst_liab -= used
    sgst_itc -= used

    return {
        "net_igst": round(igst_liab, 2),
        "net_cgst": round(cgst_liab, 2),
        "net_sgst": round(sgst_liab, 2),
        "remaining_itc": {
            "igst": round(igst_itc, 2),
            "cgst": round(cgst_itc, 2),
            "sgst": round(sgst_itc, 2),
        },
    }


@router.get("/summary", summary="GST summary — output tax, ITC, rate-wise breakup", dependencies=[require_perm("gst.read")])
async def gst_summary(
    current: CurrentUserDep, db: DBDep, month: str = Query(...),
    branch_id: UUID | None = Query(None, description="Filter to one branch/GSTIN — omit for company-wide"),
) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)
    bid = str(branch_id) if branch_id else None
    # A branch-scoped user can only ever see their own branch's GST figures —
    # each branch GSTIN files its own return, so cross-branch numbers would
    # be meaningless (and, if the state differs, wrong) to show them anyway.
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = str(current.branch_id)

    totals = (await db.execute(text(f"""
        SELECT {_signed('taxable_amount', 'sales_taxable')},
               {_signed('cgst_amount+sgst_amount+igst_amount', 'output_gst')}
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN {_GST_INVOICE_TYPES}
          AND reverse_charge = false AND is_export = false AND supply_category = 'taxable'
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    itc = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}),0) AS input_tax_credit
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = true
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    itc_blocked = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}),0) AS itc_ineligible
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = false
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    rate_wise = (await db.execute(text(f"""
        SELECT ii.gst_rate, {_signed_ii('taxable_amount', 'taxable')},
               {_signed_ii('cgst_amount', 'cgst')}, {_signed_ii('sgst_amount', 'sgst')},
               {_signed_ii('igst_amount', 'igst')},
               {_signed_ii('cgst_amount+sgst_amount+igst_amount', 'total_tax')}
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.branch_id IS NOT DISTINCT FROM COALESCE(:bid, i.branch_id)
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type IN {_GST_INVOICE_TYPES}
          AND i.reverse_charge = false AND i.is_export = false AND i.supply_category = 'taxable'
        GROUP BY ii.gst_rate ORDER BY ii.gst_rate
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    return ok(data=_clean({
        "sales_taxable": totals["sales_taxable"],
        "output_gst": totals["output_gst"],
        "input_tax_credit": itc["input_tax_credit"],
        "itc_ineligible": itc_blocked["itc_ineligible"],
        "rate_wise": [dict(r) for r in rate_wise],
        "branch_id": bid,
    }))


@router.get("/gstr1", summary="GSTR-1 — B2B, B2C, CDNR breakdown", dependencies=[require_perm("gst.read")])
async def gstr1(
    current: CurrentUserDep, db: DBDep, month: str = Query(...),
    branch_id: UUID | None = Query(None, description="Filter to one branch/GSTIN — omit for company-wide"),
) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)
    bid = str(branch_id) if branch_id else None
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = str(current.branch_id)

    b2b = (await db.execute(text("""
        SELECT i.invoice_no, i.invoice_date, i.billing_name, i.billing_gstin,
               i.taxable_amount, i.cgst_amount, i.sgst_amount, i.igst_amount, i.total_amount
        FROM invoices i
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.branch_id IS NOT DISTINCT FROM COALESCE(:bid, i.branch_id)
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type = 'tax_invoice'
          AND i.billing_gstin IS NOT NULL AND i.billing_gstin != ''
          AND is_export = false
        ORDER BY i.invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    b2c = (await db.execute(text("""
        SELECT CASE WHEN i.supply_type = 'inter' AND i.total_amount > 250000 THEN 'B2CL' ELSE 'B2CS' END AS category,
               COUNT(*) AS invoice_count, SUM(i.taxable_amount) AS taxable,
               SUM(i.cgst_amount+i.sgst_amount+i.igst_amount) AS total_tax
        FROM invoices i
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.branch_id IS NOT DISTINCT FROM COALESCE(:bid, i.branch_id)
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type = 'tax_invoice'
          AND (i.billing_gstin IS NULL OR i.billing_gstin = '')
          AND is_export = false
        GROUP BY 1
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    cdnr = (await db.execute(text("""
        SELECT i.invoice_no, i.invoice_date, i.invoice_type, i.billing_name, i.billing_gstin,
               i.taxable_amount, i.cgst_amount+i.sgst_amount+i.igst_amount AS total_tax, i.total_amount,
               i.against_invoice_id
        FROM invoices i
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.branch_id IS NOT DISTINCT FROM COALESCE(:bid, i.branch_id)
          AND i.status NOT IN ('draft','cancelled','void')
          AND i.invoice_type IN ('credit_note','debit_note')
        ORDER BY i.invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    exports = (await db.execute(text("""
        SELECT invoice_no, invoice_date, billing_name, export_type, taxable_amount, total_amount
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    return ok(data=_clean({
        "b2b": [dict(r) for r in b2b],
        "b2c": [dict(r) for r in b2c],
        "cdnr": [dict(r) for r in cdnr],
        "exports": [dict(r) for r in exports],
        "branch_id": bid,
    }))


@router.get("/gstr3b", summary="GSTR-3B — monthly summary return", dependencies=[require_perm("gst.read")])
async def gstr3b(
    current: CurrentUserDep, db: DBDep, month: str = Query(...),
    branch_id: UUID | None = Query(None, description="Filter to one branch/GSTIN — omit for company-wide"),
) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)
    bid = str(branch_id) if branch_id else None
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = str(current.branch_id)

    outward_taxable = (await db.execute(text(f"""
        SELECT
            {_signed('taxable_amount', 'taxable')},
            {_signed('cgst_amount', 'cgst')},
            {_signed('sgst_amount', 'sgst')},
            {_signed('igst_amount', 'igst')},
            {_signed('cess_amount', 'cess')}
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
        AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
        AND status NOT IN ('draft','cancelled','void')
        AND invoice_type IN {_GST_INVOICE_TYPES}
        AND reverse_charge = false AND is_export = false AND supply_category = 'taxable'
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    outward_nil_exempt = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
        AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
        AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('tax_invoice','debit_note')
        AND supply_category IN ('nil_rated','exempt')
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    outward_non_gst = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
        AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
        AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('tax_invoice','debit_note')
        AND supply_category = 'non_gst'
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    outward_zero_rated = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
        AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
        AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    inward_rcm = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst
        FROM purchase_orders
        WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND reverse_charge = true
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    itc_available = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}),0) AS cgst, COALESCE(SUM({_ITC_SGST}),0) AS sgst,
               COALESCE(SUM({_ITC_IGST}),0) AS igst
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = true
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    itc_ineligible = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}),0) AS cgst, COALESCE(SUM({_ITC_SGST}),0) AS sgst,
               COALESCE(SUM({_ITC_IGST}),0) AS igst,
               COALESCE(SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = false
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    # WPAY exports (tax paid, later refunded) still count toward this month's
    # outward liability for set-off purposes — LUT/bond exports contribute 0
    # here since their cgst/sgst/igst columns are legitimately zero.
    combined_liability = {
        "cgst": float(outward_taxable["cgst"]) + float(outward_zero_rated["cgst"]),
        "sgst": float(outward_taxable["sgst"]) + float(outward_zero_rated["sgst"]),
        "igst": float(outward_taxable["igst"]) + float(outward_zero_rated["igst"]),
    }
    setoff = _compute_setoff(combined_liability, dict(itc_available))
    net_payable = {
        "cgst": setoff["net_cgst"] + float(inward_rcm["cgst"]),
        "sgst": setoff["net_sgst"] + float(inward_rcm["sgst"]),
        "igst": setoff["net_igst"] + float(inward_rcm["igst"]),
    }

    return ok(data=_clean({
        "outward_taxable_supplies": dict(outward_taxable),
        "outward_zero_rated_supplies": dict(outward_zero_rated),
        "outward_nil_rated_exempt_supplies": dict(outward_nil_exempt),   # Table 3.1(c)
        "outward_non_gst_supplies": dict(outward_non_gst),               # Table 3.1(e)
        "inward_supplies_liable_to_rcm": dict(inward_rcm),
        "itc_available": dict(itc_available),
        "itc_ineligible_blocked_17_5": dict(itc_ineligible),   # Table 4(B) — must be reversed, not claimed
        "net_tax_payable": net_payable,
        "branch_id": bid,
    }))


@router.get("/hsn-summary", summary="HSN/SAC-wise summary", dependencies=[require_perm("gst.read")])
async def hsn_summary(
    current: CurrentUserDep, db: DBDep, month: str = Query(...),
    branch_id: UUID | None = Query(None, description="Filter to one branch/GSTIN — omit for company-wide"),
) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)
    bid = str(branch_id) if branch_id else None
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = str(current.branch_id)

    rows = (await db.execute(text(f"""
        SELECT COALESCE(ii.hsn_code, ii.sac_code, 'N/A') AS hsn, MIN(ii.description) AS description,
               ii.gst_rate,
               COALESCE(SUM(CASE WHEN i.invoice_type='credit_note' THEN -ii.quantity ELSE ii.quantity END),0) AS total_qty,
               {_signed_ii('taxable_amount', 'taxable')},
               {_signed_ii('cgst_amount', 'cgst')}, {_signed_ii('sgst_amount', 'sgst')}, {_signed_ii('igst_amount', 'igst')},
               {_signed_ii('cgst_amount+sgst_amount+igst_amount', 'total_tax')}
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.branch_id IS NOT DISTINCT FROM COALESCE(:bid, i.branch_id)
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type IN {_GST_INVOICE_TYPES}
          AND i.reverse_charge = false AND i.is_export = false AND i.supply_category = 'taxable'
        GROUP BY COALESCE(ii.hsn_code, ii.sac_code, 'N/A'), ii.gst_rate
        ORDER BY taxable DESC
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    return ok(data=_clean({"items": [dict(r) for r in rows], "branch_id": bid}))


@router.get("/itc-ledger", summary="Input Tax Credit available this period", dependencies=[require_perm("gst.read")])
async def itc_ledger(
    current: CurrentUserDep, db: DBDep, month: str = Query(...),
    branch_id: UUID | None = Query(None, description="Filter to one branch/GSTIN — omit for company-wide"),
) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)
    bid = str(branch_id) if branch_id else None
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = str(current.branch_id)

    by_vendor = (await db.execute(text(f"""
        SELECT COALESCE(p.display_name, 'Unknown') AS vendor_name, po.po_no, po.po_date,
               SUM(poi.taxable_amount * (poi.received_qty - poi.returned_qty) / NULLIF(poi.quantity, 0)) AS taxable_amount,
               SUM({_ITC_CGST}) AS cgst_amount,
               SUM({_ITC_SGST}) AS sgst_amount, SUM({_ITC_IGST}) AS igst_amount,
               SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}) AS total_itc
        FROM purchase_order_items poi
        JOIN purchase_orders po ON po.id = poi.po_id
        LEFT JOIN parties p ON p.id = po.vendor_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = true
        GROUP BY p.display_name, po.po_no, po.po_date
        ORDER BY po.po_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    ineligible_by_vendor = (await db.execute(text(f"""
        SELECT COALESCE(p.display_name, 'Unknown') AS vendor_name, po.po_no, po.po_date,
               poi.description, poi.itc_ineligible_reason,
               SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}) AS blocked_amount
        FROM purchase_order_items poi
        JOIN purchase_orders po ON po.id = poi.po_id
        LEFT JOIN parties p ON p.id = po.vendor_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = false
        GROUP BY p.display_name, po.po_no, po.po_date, poi.description, poi.itc_ineligible_reason
        ORDER BY po.po_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    totals = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}),0) AS cgst, COALESCE(SUM({_ITC_SGST}),0) AS sgst,
               COALESCE(SUM({_ITC_IGST}),0) AS igst,
               COALESCE(SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = true
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    ineligible_totals = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}),0) AS cgst, COALESCE(SUM({_ITC_SGST}),0) AS sgst,
               COALESCE(SUM({_ITC_IGST}),0) AS igst,
               COALESCE(SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = false
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    return ok(data=_clean({
        "totals": dict(totals),
        "by_vendor": [dict(r) for r in by_vendor],
        "ineligible_totals": dict(ineligible_totals),
        "ineligible_by_vendor": [dict(r) for r in ineligible_by_vendor],
        "note": "Only itc_eligible line items are counted as claimable ITC. Ineligible items (Section 17(5) blocked credits) are shown separately and must be reversed, not claimed.",
        "branch_id": bid,
    }))


@router.post("/gstr3b/file", summary="File GSTR-3B for a period (snapshot + lock)", dependencies=[require_perm("gst.file")])
async def file_gstr3b(
    current: CurrentUserDep, db: DBDep, month: str = Query(...),
    branch_id: UUID | None = Query(None, description="Branch/GSTIN this filing is for — omit for company-wide"),
) -> ORJSONResponse:
    cid = current.company_id
    df, dt = _month_bounds(month)
    bid_uuid = branch_id
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid_uuid = current.branch_id
        from app.api.v1.dependencies import assert_branch_access
        assert_branch_access(current, bid_uuid)
    bid = str(bid_uuid) if bid_uuid else None

    existing = (await db.execute(text(
        "SELECT status FROM gst_returns WHERE company_id=:cid AND branch_id IS NOT DISTINCT FROM :bid "
        "AND return_type='GSTR-3B' AND period_from=:df"
    ), {"cid": str(cid), "bid": bid, "df": df})).scalar()
    if existing == "filed":
        return ok(message="This period is already filed for this branch.", data={"status": "filed"})

    outward = (await db.execute(text(f"""
        SELECT
            {_signed('taxable_amount', 'taxable')},
            {_signed('cgst_amount', 'cgst')},
            {_signed('sgst_amount', 'sgst')},
            {_signed('igst_amount', 'igst')}
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void')
          AND invoice_type IN {_GST_INVOICE_TYPES}
          AND reverse_charge = false AND supply_category = 'taxable'
    """), {"cid": str(cid), "df": df, "dt": dt, "bid": bid})).mappings().one()

    nil_exempt = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND supply_category IN ('nil_rated','exempt')
    """), {"cid": str(cid), "df": df, "dt": dt, "bid": bid})).mappings().one()

    non_gst = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND supply_category = 'non_gst'
    """), {"cid": str(cid), "df": df, "dt": dt, "bid": bid})).mappings().one()

    inward_rcm = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst
        FROM purchase_orders WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND reverse_charge = true
    """), {"cid": str(cid), "df": df, "dt": dt, "bid": bid})).mappings().one()

    itc = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}),0) AS cgst, COALESCE(SUM({_ITC_SGST}),0) AS sgst,
               COALESCE(SUM({_ITC_IGST}),0) AS igst
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = true
    """), {"cid": str(cid), "df": df, "dt": dt, "bid": bid})).mappings().one()

    itc_ineligible = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}),0) AS cgst, COALESCE(SUM({_ITC_SGST}),0) AS sgst,
               COALESCE(SUM({_ITC_IGST}),0) AS igst,
               COALESCE(SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = false
    """), {"cid": str(cid), "df": df, "dt": dt, "bid": bid})).mappings().one()

    setoff = _compute_setoff(dict(outward), dict(itc))
    # RCM liability is always paid in cash — it is never netted against ITC.
    rcm_cash = float(inward_rcm["cgst"]) + float(inward_rcm["sgst"]) + float(inward_rcm["igst"])
    total_payable = setoff["net_cgst"] + setoff["net_sgst"] + setoff["net_igst"] + rcm_cash

    gst_return = GSTReturn(
        company_id=cid, branch_id=bid_uuid, return_type="GSTR-3B", period_from=df, period_to=dt,
        financial_year=f"{df.year}-{str(df.year+1)[2:]}" if df.month >= 4 else f"{df.year-1}-{str(df.year)[2:]}",
        taxable_turnover=outward["taxable"],
        exempt_turnover=nil_exempt["taxable"],
        nil_turnover=non_gst["taxable"],
        total_cgst_output=outward["cgst"], total_sgst_output=outward["sgst"], total_igst_output=outward["igst"],
        itc_cgst=itc["cgst"], itc_sgst=itc["sgst"], itc_igst=itc["igst"],
        net_cgst_payable=setoff["net_cgst"], net_sgst_payable=setoff["net_sgst"], net_igst_payable=setoff["net_igst"],
        total_tax_payable=total_payable, status="filed", filed_at=dt_now.utcnow(), filed_by=current.user_id,
        json_data={
            "inward_rcm_liability": {"taxable": float(inward_rcm["taxable"]), "cgst": float(inward_rcm["cgst"]),
                                      "sgst": float(inward_rcm["sgst"]), "igst": float(inward_rcm["igst"]),
                                      "cash_payable": rcm_cash},
            "itc_ineligible_17_5": {"cgst": float(itc_ineligible["cgst"]), "sgst": float(itc_ineligible["sgst"]),
                                     "igst": float(itc_ineligible["igst"]), "total": float(itc_ineligible["total"])},
        },
    )
    db.add(gst_return)
    await db.flush()

    return ok(data=_clean({
        "status": "filed", "filed_at": gst_return.filed_at, "net_payable": setoff,
        "remaining_itc": setoff["remaining_itc"],
        "inward_rcm_liability": dict(inward_rcm) | {"cash_payable": rcm_cash},
        "itc_ineligible_17_5": dict(itc_ineligible),
        "total_cash_payable": total_payable,
        "branch_id": bid,
    }), message=f"GSTR-3B filed for {month}" + (f" (branch {bid})." if bid else "."))


@router.get("/filed-returns", summary="History of filed GST returns", dependencies=[require_perm("gst.read")])
async def filed_returns(
    current: CurrentUserDep, db: DBDep,
    branch_id: UUID | None = Query(None, description="Filter to one branch/GSTIN — omit for company-wide"),
) -> ORJSONResponse:
    bid = str(branch_id) if branch_id else None
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = str(current.branch_id)

    rows = (await db.execute(text("""
        SELECT return_type, branch_id, period_from, period_to, taxable_turnover, total_tax_payable,
               net_cgst_payable, net_sgst_payable, net_igst_payable, status, filed_at, arn
        FROM gst_returns
        WHERE company_id=:cid AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
        ORDER BY period_from DESC
    """), {"cid": str(current.company_id), "bid": bid})).mappings().all()
    return ok(data=_clean({"returns": [dict(r) for r in rows]}))

@router.get("/report/pdf", summary="Download GST Compliance Report as PDF", dependencies=[require_perm("gst.export")])
async def gst_report_pdf(
    current: CurrentUserDep, db: DBDep, month: str = Query(...),
    branch_id: UUID | None = Query(None, description="Filter to one branch/GSTIN — omit for company-wide"),
) -> Response:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)
    bid = str(branch_id) if branch_id else None
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = str(current.branch_id)

    if bid:
        # A branch has its own GSTIN and address — the report header must show
        # that branch's registration details, not the company's, or the PDF
        # would carry the wrong GSTIN for whoever files it.
        company_row = (await db.execute(
            text("SELECT branch_name AS legal_name, address AS reg_address, gstin, phone, email, "
                 "NULL AS website FROM branches WHERE id = :bid"),
            {"bid": bid}
        )).mappings().one_or_none() or {}
    else:
        company_row = (await db.execute(
            text("SELECT legal_name, reg_address, gstin, phone, email, website FROM companies WHERE id = :cid"),
            {"cid": cid}
        )).mappings().one_or_none() or {}

    # 3.1(a) Taxable outward supplies — net of credit notes, whitelisted invoice types only
    outward = (await db.execute(text(f"""
        SELECT {_signed('taxable_amount', 'taxable')}, {_signed('cgst_amount', 'cgst')},
               {_signed('sgst_amount', 'sgst')}, {_signed('igst_amount', 'igst')},
               {_signed('cess_amount', 'cess')}
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN {_GST_INVOICE_TYPES}
          AND reverse_charge = false AND is_export = false AND supply_category = 'taxable'
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()
    totals = {"sales_taxable": outward["taxable"],
              "output_gst": float(outward["cgst"]) + float(outward["sgst"]) + float(outward["igst"])}

    # 3.1(b) Zero-rated (export) supplies
    zero_rated = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    # 3.1(c) Nil-rated / exempt supplies
    nil_exempt = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('tax_invoice','debit_note')
          AND supply_category IN ('nil_rated','exempt')
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    # 3.1(e) Non-GST supplies
    non_gst = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('tax_invoice','debit_note')
          AND supply_category = 'non_gst'
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    # 3.1(d) Inward supplies liable to reverse charge
    inward_rcm = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst
        FROM purchase_orders WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND reverse_charge = true
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    # 4(A) Eligible ITC — from PO line items only, itc_eligible=true, net of any Rule-37
    # reversal for goods already returned to the vendor. (Was incorrectly pulling
    # header-level totals off purchase_orders with no eligibility filter at all.)
    itc = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}),0) AS cgst, COALESCE(SUM({_ITC_SGST}),0) AS sgst,
               COALESCE(SUM({_ITC_IGST}),0) AS igst
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = true
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    # 4(B) Ineligible / blocked ITC (Section 17(5)) — must be reversed, never claimed
    itc_ineligible = (await db.execute(text(f"""
        SELECT COALESCE(SUM({_ITC_CGST}),0) AS cgst, COALESCE(SUM({_ITC_SGST}),0) AS sgst,
               COALESCE(SUM({_ITC_IGST}),0) AS igst,
               COALESCE(SUM({_ITC_CGST}+{_ITC_SGST}+{_ITC_IGST}),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND po.branch_id IS NOT DISTINCT FROM COALESCE(:bid, po.branch_id)
          AND poi.itc_eligible = false
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().one()

    # Proper Section 49A/49B set-off order (IGST ITC first, CGST/SGST ITC never
    # cross-offset each other) — same helper used by /gstr3b and /gstr3b/file,
    # instead of the old flat max(0, outward - itc) per head. WPAY export tax
    # (zero_rated) is real liability too and must be folded in here — LUT/bond
    # exports contribute 0 since their tax columns are legitimately zero.
    combined_liability = {
        "cgst": float(outward["cgst"]) + float(zero_rated["cgst"]),
        "sgst": float(outward["sgst"]) + float(zero_rated["sgst"]),
        "igst": float(outward["igst"]) + float(zero_rated["igst"]),
    }
    setoff = _compute_setoff(combined_liability, dict(itc))
    rcm_cash = float(inward_rcm["cgst"]) + float(inward_rcm["sgst"]) + float(inward_rcm["igst"])
    net = {"cgst": setoff["net_cgst"], "sgst": setoff["net_sgst"], "igst": setoff["net_igst"]}
    total_cash_payable = setoff["net_cgst"] + setoff["net_sgst"] + setoff["net_igst"] + rcm_cash

    b2b = (await db.execute(text("""
        SELECT invoice_no, invoice_date, billing_name, billing_gstin, taxable_amount, total_amount
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND billing_gstin IS NOT NULL AND billing_gstin != '' AND is_export = false
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    b2c = (await db.execute(text("""
        SELECT CASE WHEN supply_type='inter' AND total_amount>250000 THEN 'B2CL' ELSE 'B2CS' END AS category,
               COUNT(*) AS invoice_count, SUM(taxable_amount) AS taxable,
               SUM(cgst_amount+sgst_amount+igst_amount) AS total_tax
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND (billing_gstin IS NULL OR billing_gstin = '') AND is_export = false
        GROUP BY 1
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    cdnr = (await db.execute(text("""
        SELECT invoice_no, invoice_date, invoice_type, billing_name, taxable_amount, total_amount
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('credit_note','debit_note')
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    exports = (await db.execute(text("""
        SELECT invoice_no, invoice_date, billing_name, export_type, taxable_amount
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    hsn = (await db.execute(text(f"""
        SELECT COALESCE(ii.hsn_code, ii.sac_code, 'N/A') AS hsn, MIN(ii.description) AS description,
               ii.gst_rate,
               COALESCE(SUM(CASE WHEN i.invoice_type='credit_note' THEN -ii.quantity ELSE ii.quantity END),0) AS qty,
               {_signed_ii('taxable_amount', 'taxable')},
               {_signed_ii('cgst_amount+sgst_amount+igst_amount', 'total_tax')}
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.branch_id IS NOT DISTINCT FROM COALESCE(:bid, i.branch_id)
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type IN {_GST_INVOICE_TYPES}
          AND i.reverse_charge = false AND i.is_export = false AND i.supply_category = 'taxable'
        GROUP BY COALESCE(ii.hsn_code, ii.sac_code, 'N/A'), ii.gst_rate ORDER BY taxable DESC
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    pdf_bytes = generate_report_pdf(
        title="GST Compliance Report",
        subtitle=f"Period: {month}",
        summary=[
            ("Sales (Taxable)", format_inr(totals["sales_taxable"]), "blue"),
            ("Output GST", format_inr(totals["output_gst"]), "green"),
            ("Eligible ITC", format_inr(float(itc["cgst"]) + float(itc["sgst"]) + float(itc["igst"])), "orange"),
            ("Net Cash Payable", format_inr(total_cash_payable), "red"),
        ],
        tables=[
            ("3.1(a) Outward Taxable Supplies (net of credit notes)",
             ["Taxable Value", "CGST", "SGST", "IGST", "Cess"],
             [[format_inr(outward["taxable"]), format_inr(outward["cgst"]), format_inr(outward["sgst"]),
               format_inr(outward["igst"]), format_inr(outward["cess"])]]),
            ("3.1(b) Zero-Rated (Export) Supplies", ["Taxable Value", "CGST", "SGST", "IGST"],
             [[format_inr(zero_rated["taxable"]), format_inr(zero_rated["cgst"]),
               format_inr(zero_rated["sgst"]), format_inr(zero_rated["igst"])]]),
            ("3.1(c) Nil-Rated / Exempt Supplies", ["Taxable Value"],
             [[format_inr(nil_exempt["taxable"])]]),
            ("3.1(d) Inward Supplies Liable to Reverse Charge", ["Taxable Value", "CGST", "SGST", "IGST"],
             [[format_inr(inward_rcm["taxable"]), format_inr(inward_rcm["cgst"]),
               format_inr(inward_rcm["sgst"]), format_inr(inward_rcm["igst"])]]),
            ("3.1(e) Non-GST Supplies", ["Taxable Value"],
             [[format_inr(non_gst["taxable"])]]),
            ("4(A) Eligible Input Tax Credit (ITC)", ["CGST", "SGST", "IGST"],
             [[format_inr(itc["cgst"]), format_inr(itc["sgst"]), format_inr(itc["igst"])]]),
            ("4(B) Ineligible / Blocked ITC — Section 17(5)", ["CGST", "SGST", "IGST", "Total"],
             [[format_inr(itc_ineligible["cgst"]), format_inr(itc_ineligible["sgst"]),
               format_inr(itc_ineligible["igst"]), format_inr(itc_ineligible["total"])]]),
            ("Net Tax Payable (after Sec 49A/49B set-off)", ["CGST", "SGST", "IGST", "RCM (cash only)", "Total Cash Payable"],
             [[format_inr(net["cgst"]), format_inr(net["sgst"]), format_inr(net["igst"]),
               format_inr(rcm_cash), format_inr(total_cash_payable)]]),
            ("GSTR-1 — B2B Invoices (Registered)", ["Invoice No", "Date", "Customer", "GSTIN", "Taxable", "Total"],
             [[r["invoice_no"], str(r["invoice_date"]), r["billing_name"], r["billing_gstin"],
               format_inr(r["taxable_amount"]), format_inr(r["total_amount"])] for r in b2b]),
            ("GSTR-1 — B2C Summary (Unregistered)", ["Category", "Invoices", "Taxable", "Total Tax"],
             [[r["category"], str(r["invoice_count"]), format_inr(r["taxable"]), format_inr(r["total_tax"])] for r in b2c]),
            ("GSTR-1 — CDNR (Credit/Debit Notes)", ["Note No", "Date", "Type", "Customer", "Taxable", "Total"],
             [[r["invoice_no"], str(r["invoice_date"]), r["invoice_type"], r["billing_name"],
               format_inr(r["taxable_amount"]), format_inr(r["total_amount"])] for r in cdnr]),
            ("GSTR-1 — Exports", ["Invoice No", "Date", "Customer", "Export Type", "Taxable"],
             [[r["invoice_no"], str(r["invoice_date"]), r["billing_name"], r["export_type"],
               format_inr(r["taxable_amount"])] for r in exports]),
            ("HSN/SAC-wise Summary", ["HSN/SAC", "Description", "Rate", "Qty", "Taxable", "Total Tax"],
             [[r["hsn"], r["description"], f"{r['gst_rate']}%", f"{float(r['qty']):.0f}",
               format_inr(r["taxable"]), format_inr(r["total_tax"])] for r in hsn]),
        ],
        company=dict(company_row),
        period=month,
        generated_by=current.full_name if hasattr(current, "full_name") else "System",
    )
    return Response(content=pdf_bytes, media_type="application/pdf",
                     headers={"Content-Disposition": f'attachment; filename="gst_report_{month}.pdf"'})

@router.get("/gstr1/json", summary="Export GSTR-1 in GSTN Offline Utility JSON format", dependencies=[require_perm("gst.export")])
async def gstr1_json_export(
    current: CurrentUserDep, db: DBDep, month: str = Query(...),
    branch_id: UUID | None = Query(None, description="Branch/GSTIN to export — omit for company-wide"),
) -> Response:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)
    bid = str(branch_id) if branch_id else None
    if current.branch_id is not None and not current.has_permission("branch.access_all"):
        bid = str(current.branch_id)

    # The filing GSTIN must be the branch's own registration when one is
    # selected — using the company's GSTIN here for a branch filing would
    # produce a JSON file that gets rejected (or worse, silently misfiled)
    # on the GSTN portal.
    if bid:
        company_row = (await db.execute(
            text("SELECT gstin FROM branches WHERE id = :bid"), {"bid": bid}
        )).mappings().one_or_none() or {}
    else:
        company_row = (await db.execute(
            text("SELECT gstin FROM companies WHERE id = :cid"), {"cid": cid}
        )).mappings().one_or_none() or {}
    gstin = company_row.get("gstin", "")

    def _fmt_date(d) -> str:
        return d.strftime("%d-%m-%Y") if d else ""

    b2b_rows = (await db.execute(text("""
        SELECT invoice_no, invoice_date, billing_gstin, billing_state_code, total_amount,
               taxable_amount, cgst_amount, sgst_amount, igst_amount, cess_amount, supply_type
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND billing_gstin IS NOT NULL AND billing_gstin != '' AND is_export = false
        ORDER BY billing_gstin, invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    b2b_by_gstin: dict[str, list] = {}
    for r in b2b_rows:
        b2b_by_gstin.setdefault(r["billing_gstin"], []).append({
            "inum": r["invoice_no"],
            "idt": _fmt_date(r["invoice_date"]),
            "val": float(r["total_amount"]),
            "pos": r["billing_state_code"] or "",
            "rchrg": "N",
            "inv_typ": "R",
            "itms": [{
                "num": 1,
                "itm_det": {
                    "txval": float(r["taxable_amount"]),
                    "camt": float(r["cgst_amount"]),
                    "samt": float(r["sgst_amount"]),
                    "iamt": float(r["igst_amount"]),
                    "csamt": float(r["cess_amount"]),
                }
            }],
        })
    b2b = [{"ctin": gstin_key, "inv": invs} for gstin_key, invs in b2b_by_gstin.items()]

    b2cs_rows = (await db.execute(text("""
        SELECT billing_state_code AS pos, supply_type,
               SUM(taxable_amount) AS txval, SUM(cgst_amount) AS camt,
               SUM(sgst_amount) AS samt, SUM(igst_amount) AS iamt
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND (billing_gstin IS NULL OR billing_gstin = '') AND is_export = false
        GROUP BY billing_state_code, supply_type
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    b2cs = [{
        "sply_ty": "INTER" if r["supply_type"] == "inter" else "INTRA",
        "pos": r["pos"] or "",
        "typ": "OE",
        "txval": float(r["txval"]),
        "camt": float(r["camt"]),
        "samt": float(r["samt"]),
        "iamt": float(r["iamt"]),
    } for r in b2cs_rows]

    cdnr_rows = (await db.execute(text("""
        SELECT invoice_no, invoice_date, invoice_type, billing_gstin, billing_state_code,
               total_amount, taxable_amount, cgst_amount, sgst_amount, igst_amount, cess_amount
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('credit_note','debit_note')
        ORDER BY billing_gstin, invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    # Real GSTR-1 has no bucket for credit/debit notes against unregistered
    # customers (CDNR is B2B-only by definition) — group those under a
    # placeholder key instead of silently dropping them, so at least nothing
    # goes missing from the export. Flag them for manual review before upload.
    cdnr_by_gstin: dict[str, list] = {}
    for r in cdnr_rows:
        gstin_key = r["billing_gstin"] or "UNREGISTERED"
        cdnr_by_gstin.setdefault(gstin_key, []).append({
            "nt_num": r["invoice_no"],
            "nt_dt": _fmt_date(r["invoice_date"]),
            "ntty": "C" if r["invoice_type"] == "credit_note" else "D",
            "val": float(r["total_amount"]),
            "pos": r["billing_state_code"] or "",
            "itms": [{
                "num": 1,
                "itm_det": {
                    "txval": float(r["taxable_amount"]),
                    "camt": float(r["cgst_amount"]),
                    "samt": float(r["sgst_amount"]),
                    "iamt": float(r["igst_amount"]),
                    "csamt": float(r["cess_amount"]),
                }
            }],
        })
    cdnr = [{"ctin": gstin_key, "nt": notes} for gstin_key, notes in cdnr_by_gstin.items()]

    exp_rows = (await db.execute(text("""
        SELECT invoice_no, invoice_date, export_type, total_amount, taxable_amount, igst_amount
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND branch_id IS NOT DISTINCT FROM COALESCE(:bid, branch_id)
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    exp_by_type: dict[str, list] = {}
    for r in exp_rows:
        exp_by_type.setdefault(r["export_type"] or "WPAY", []).append({
            "inum": r["invoice_no"], "idt": _fmt_date(r["invoice_date"]),
            "val": float(r["total_amount"]), "sbpcode": "", "sbnum": "", "sbdt": "",
            "itms": [{"txval": float(r["taxable_amount"]), "iamt": float(r["igst_amount"])}],
        })
    exp = [{"exp_typ": t, "inv": invs} for t, invs in exp_by_type.items()]

    hsn_rows = (await db.execute(text(f"""
        SELECT COALESCE(ii.hsn_code, ii.sac_code, '') AS hsn, MIN(ii.description) AS desc,
               ii.gst_rate AS rt,
               COALESCE(SUM(CASE WHEN i.invoice_type='credit_note' THEN -ii.quantity ELSE ii.quantity END),0) AS qty,
               {_signed_ii('taxable_amount', 'txval')},
               {_signed_ii('cgst_amount', 'camt')}, {_signed_ii('sgst_amount', 'samt')}, {_signed_ii('igst_amount', 'iamt')}
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.branch_id IS NOT DISTINCT FROM COALESCE(:bid, i.branch_id)
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type IN {_GST_INVOICE_TYPES}
          AND i.reverse_charge = false AND i.is_export = false AND i.supply_category = 'taxable'
        GROUP BY COALESCE(ii.hsn_code, ii.sac_code, ''), ii.gst_rate
    """), {"cid": cid, "df": df, "dt": dt, "bid": bid})).mappings().all()

    hsn_data = [{
        "num": i + 1, "hsn_sc": r["hsn"], "desc": r["desc"], "uqc": "NOS",
        "qty": float(r["qty"]), "val": float(r["txval"]) + float(r["camt"]) + float(r["samt"]) + float(r["iamt"]),
        "txval": float(r["txval"]), "iamt": float(r["iamt"]), "camt": float(r["camt"]),
        "samt": float(r["samt"]), "csamt": 0, "rt": float(r["rt"]),
    } for i, r in enumerate(hsn_rows)]

    fp = f"{month[5:7]}{month[0:4]}"  # GSTN format: MMYYYY

    gstr1_json = {
        "gstin": gstin,
        "fp": fp,
        "version": "GST3.2.3",
        "hash": "hash not computed - offline-tool signature required for portal upload",
        "b2b": b2b,
        "b2cs": b2cs,
        "cdnr": cdnr,
        "exp": exp,
        "hsn": {"data": hsn_data},
    }

    import json
    body = json.dumps(gstr1_json, indent=2)
    return Response(content=body, media_type="application/json",
                     headers={"Content-Disposition": f'attachment; filename="GSTR1_{fp}.json"'})