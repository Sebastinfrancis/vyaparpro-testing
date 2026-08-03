"""VyaparPro — GST Compliance Reports (live-computed, read-only)"""
from __future__ import annotations
from datetime import date
import calendar
from app import db
from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse
from sqlalchemy import text

from app.api.v1.dependencies import CurrentUserDep, DBDep
from app.utils.responses import ok
from datetime import datetime as dt_now
from app.db.models.accounting import GSTReturn
from fastapi.responses import Response
from app.utils.pdf_generator import generate_report_pdf, format_inr

router = APIRouter()


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


@router.get("/summary", summary="GST summary — output tax, ITC, rate-wise breakup")
async def gst_summary(current: CurrentUserDep, db: DBDep, month: str = Query(...)) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)

    totals = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS sales_taxable,
               COALESCE(SUM(cgst_amount+sgst_amount+igst_amount),0) AS output_gst
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type != 'credit_note' AND reverse_charge = false
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    itc = (await db.execute(text("""
        SELECT COALESCE(SUM(poi.cgst_amount+poi.sgst_amount+poi.igst_amount),0) AS input_tax_credit
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = true
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    itc_blocked = (await db.execute(text("""
        SELECT COALESCE(SUM(poi.cgst_amount+poi.sgst_amount+poi.igst_amount),0) AS itc_ineligible
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = false
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    rate_wise = (await db.execute(text("""
        SELECT ii.gst_rate, SUM(ii.taxable_amount) AS taxable,
               SUM(ii.cgst_amount) AS cgst, SUM(ii.sgst_amount) AS sgst,
               SUM(ii.igst_amount) AS igst, SUM(ii.cgst_amount+ii.sgst_amount+ii.igst_amount) AS total_tax
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type != 'credit_note'
        GROUP BY ii.gst_rate ORDER BY ii.gst_rate
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    return ok(data=_clean({
        "sales_taxable": totals["sales_taxable"],
        "output_gst": totals["output_gst"],
        "input_tax_credit": itc["input_tax_credit"],
        "itc_ineligible": itc_blocked["itc_ineligible"],
        "rate_wise": [dict(r) for r in rate_wise],
    }))


@router.get("/gstr1", summary="GSTR-1 — B2B, B2C, CDNR breakdown")
async def gstr1(current: CurrentUserDep, db: DBDep, month: str = Query(...)) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)

    b2b = (await db.execute(text("""
        SELECT i.invoice_no, i.invoice_date, i.billing_name, i.billing_gstin,
               i.taxable_amount, i.cgst_amount, i.sgst_amount, i.igst_amount, i.total_amount
        FROM invoices i
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type = 'tax_invoice'
          AND i.billing_gstin IS NOT NULL AND i.billing_gstin != ''
          AND is_export = false
        ORDER BY i.invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    b2c = (await db.execute(text("""
        SELECT CASE WHEN i.supply_type = 'inter' AND i.total_amount > 250000 THEN 'B2CL' ELSE 'B2CS' END AS category,
               COUNT(*) AS invoice_count, SUM(i.taxable_amount) AS taxable,
               SUM(i.cgst_amount+i.sgst_amount+i.igst_amount) AS total_tax
        FROM invoices i
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type = 'tax_invoice'
          AND (i.billing_gstin IS NULL OR i.billing_gstin = '')
          AND is_export = false
        GROUP BY 1
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    cdnr = (await db.execute(text("""
        SELECT i.invoice_no, i.invoice_date, i.invoice_type, i.billing_name, i.billing_gstin,
               i.taxable_amount, i.cgst_amount+i.sgst_amount+i.igst_amount AS total_tax, i.total_amount,
               i.against_invoice_id
        FROM invoices i
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void')
          AND i.invoice_type IN ('credit_note','debit_note')
          AND i.billing_gstin IS NOT NULL AND i.billing_gstin != ''
        ORDER BY i.invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    exports = (await db.execute(text("""
        SELECT invoice_no, invoice_date, billing_name, export_type, taxable_amount, total_amount
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    return ok(data=_clean({
        "b2b": [dict(r) for r in b2b],
        "b2c": [dict(r) for r in b2c],
        "cdnr": [dict(r) for r in cdnr],
        "exports": [dict(r) for r in exports],
    }))


@router.get("/gstr3b", summary="GSTR-3B — monthly summary return")
async def gstr3b(current: CurrentUserDep, db: DBDep, month: str = Query(...)) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)

    outward_taxable = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
            COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst,
            COALESCE(SUM(cess_amount),0) AS cess
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
        AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('tax_invoice','debit_note')
        AND reverse_charge = false AND is_export = false AND supply_category = 'taxable'
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    outward_nil_exempt = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
        AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('tax_invoice','debit_note')
        AND supply_category IN ('nil_rated','exempt')
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    outward_non_gst = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
        AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('tax_invoice','debit_note')
        AND supply_category = 'non_gst'
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    outward_zero_rated = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
        AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    inward_rcm = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst
        FROM purchase_orders
        WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
          AND reverse_charge = true
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    itc_available = (await db.execute(text("""
        SELECT COALESCE(SUM(poi.cgst_amount),0) AS cgst, COALESCE(SUM(poi.sgst_amount),0) AS sgst,
               COALESCE(SUM(poi.igst_amount),0) AS igst
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = true
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    itc_ineligible = (await db.execute(text("""
        SELECT COALESCE(SUM(poi.cgst_amount),0) AS cgst, COALESCE(SUM(poi.sgst_amount),0) AS sgst,
               COALESCE(SUM(poi.igst_amount),0) AS igst,
               COALESCE(SUM(poi.cgst_amount+poi.sgst_amount+poi.igst_amount),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = false
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    net_payable = {
        "cgst": max(0, float(outward_taxable["cgst"]) - float(itc_available["cgst"])) + float(inward_rcm["cgst"]),
        "sgst": max(0, float(outward_taxable["sgst"]) - float(itc_available["sgst"])) + float(inward_rcm["sgst"]),
        "igst": max(0, float(outward_taxable["igst"]) - float(itc_available["igst"])) + float(inward_rcm["igst"]),
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
    }))


@router.get("/hsn-summary", summary="HSN/SAC-wise summary")
async def hsn_summary(current: CurrentUserDep, db: DBDep, month: str = Query(...)) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)

    rows = (await db.execute(text("""
        SELECT COALESCE(ii.hsn_code, ii.sac_code, 'N/A') AS hsn, MIN(ii.description) AS description,
               ii.gst_rate, SUM(ii.quantity) AS total_qty, SUM(ii.taxable_amount) AS taxable,
               SUM(ii.cgst_amount) AS cgst, SUM(ii.sgst_amount) AS sgst, SUM(ii.igst_amount) AS igst,
               SUM(ii.cgst_amount+ii.sgst_amount+ii.igst_amount) AS total_tax
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type != 'credit_note'
        GROUP BY COALESCE(ii.hsn_code, ii.sac_code, 'N/A'), ii.gst_rate
        ORDER BY taxable DESC
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    return ok(data=_clean({"items": [dict(r) for r in rows]}))


@router.get("/itc-ledger", summary="Input Tax Credit available this period")
async def itc_ledger(current: CurrentUserDep, db: DBDep, month: str = Query(...)) -> ORJSONResponse:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)

    by_vendor = (await db.execute(text("""
        SELECT COALESCE(p.display_name, 'Unknown') AS vendor_name, po.po_no, po.po_date,
               SUM(poi.taxable_amount) AS taxable_amount, SUM(poi.cgst_amount) AS cgst_amount,
               SUM(poi.sgst_amount) AS sgst_amount, SUM(poi.igst_amount) AS igst_amount,
               SUM(poi.cgst_amount+poi.sgst_amount+poi.igst_amount) AS total_itc
        FROM purchase_order_items poi
        JOIN purchase_orders po ON po.id = poi.po_id
        LEFT JOIN parties p ON p.id = po.vendor_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = true
        GROUP BY p.display_name, po.po_no, po.po_date
        ORDER BY po.po_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    ineligible_by_vendor = (await db.execute(text("""
        SELECT COALESCE(p.display_name, 'Unknown') AS vendor_name, po.po_no, po.po_date,
               poi.description, poi.itc_ineligible_reason,
               SUM(poi.cgst_amount+poi.sgst_amount+poi.igst_amount) AS blocked_amount
        FROM purchase_order_items poi
        JOIN purchase_orders po ON po.id = poi.po_id
        LEFT JOIN parties p ON p.id = po.vendor_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = false
        GROUP BY p.display_name, po.po_no, po.po_date, poi.description, poi.itc_ineligible_reason
        ORDER BY po.po_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    totals = (await db.execute(text("""
        SELECT COALESCE(SUM(poi.cgst_amount),0) AS cgst, COALESCE(SUM(poi.sgst_amount),0) AS sgst,
               COALESCE(SUM(poi.igst_amount),0) AS igst,
               COALESCE(SUM(poi.cgst_amount+poi.sgst_amount+poi.igst_amount),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = true
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    ineligible_totals = (await db.execute(text("""
        SELECT COALESCE(SUM(poi.cgst_amount),0) AS cgst, COALESCE(SUM(poi.sgst_amount),0) AS sgst,
               COALESCE(SUM(poi.igst_amount),0) AS igst,
               COALESCE(SUM(poi.cgst_amount+poi.sgst_amount+poi.igst_amount),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = false
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    return ok(data=_clean({
        "totals": dict(totals),
        "by_vendor": [dict(r) for r in by_vendor],
        "ineligible_totals": dict(ineligible_totals),
        "ineligible_by_vendor": [dict(r) for r in ineligible_by_vendor],
        "note": "Only itc_eligible line items are counted as claimable ITC. Ineligible items (Section 17(5) blocked credits) are shown separately and must be reversed, not claimed.",
    }))


@router.post("/gstr3b/file", summary="File GSTR-3B for a period (snapshot + lock)")
async def file_gstr3b(current: CurrentUserDep, db: DBDep, month: str = Query(...)) -> ORJSONResponse:
    cid = current.company_id
    df, dt = _month_bounds(month)

    existing = (await db.execute(text(
        "SELECT status FROM gst_returns WHERE company_id=:cid AND return_type='GSTR-3B' AND period_from=:df"
    ), {"cid": str(cid), "df": df})).scalar()
    if existing == "filed":
        return ok(message="This period is already filed.", data={"status": "filed"})

    outward = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND reverse_charge = false AND supply_category = 'taxable'
    """), {"cid": str(cid), "df": df, "dt": dt})).mappings().one()

    nil_exempt = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND supply_category IN ('nil_rated','exempt')
    """), {"cid": str(cid), "df": df, "dt": dt})).mappings().one()

    non_gst = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND supply_category = 'non_gst'
    """), {"cid": str(cid), "df": df, "dt": dt})).mappings().one()

    inward_rcm = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst
        FROM purchase_orders WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
          AND reverse_charge = true
    """), {"cid": str(cid), "df": df, "dt": dt})).mappings().one()

    itc = (await db.execute(text("""
        SELECT COALESCE(SUM(poi.cgst_amount),0) AS cgst, COALESCE(SUM(poi.sgst_amount),0) AS sgst,
               COALESCE(SUM(poi.igst_amount),0) AS igst
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = true
    """), {"cid": str(cid), "df": df, "dt": dt})).mappings().one()

    itc_ineligible = (await db.execute(text("""
        SELECT COALESCE(SUM(poi.cgst_amount),0) AS cgst, COALESCE(SUM(poi.sgst_amount),0) AS sgst,
               COALESCE(SUM(poi.igst_amount),0) AS igst,
               COALESCE(SUM(poi.cgst_amount+poi.sgst_amount+poi.igst_amount),0) AS total
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
          AND poi.itc_eligible = false
    """), {"cid": str(cid), "df": df, "dt": dt})).mappings().one()

    setoff = _compute_setoff(dict(outward), dict(itc))
    # RCM liability is always paid in cash — it is never netted against ITC.
    rcm_cash = float(inward_rcm["cgst"]) + float(inward_rcm["sgst"]) + float(inward_rcm["igst"])
    total_payable = setoff["net_cgst"] + setoff["net_sgst"] + setoff["net_igst"] + rcm_cash

    gst_return = GSTReturn(
        company_id=cid, return_type="GSTR-3B", period_from=df, period_to=dt,
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
    }), message=f"GSTR-3B filed for {month}.")


@router.get("/filed-returns", summary="History of filed GST returns")
async def filed_returns(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    rows = (await db.execute(text("""
        SELECT return_type, period_from, period_to, taxable_turnover, total_tax_payable,
               net_cgst_payable, net_sgst_payable, net_igst_payable, status, filed_at, arn
        FROM gst_returns WHERE company_id=:cid ORDER BY period_from DESC
    """), {"cid": str(current.company_id)})).mappings().all()
    return ok(data=_clean({"returns": [dict(r) for r in rows]}))

@router.get("/report/pdf", summary="Download GST Compliance Report as PDF")
async def gst_report_pdf(current: CurrentUserDep, db: DBDep, month: str = Query(...)) -> Response:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)

    company_row = (await db.execute(
        text("SELECT legal_name, reg_address, gstin, phone, email, website FROM companies WHERE id = :cid"),
        {"cid": cid}
    )).mappings().one_or_none() or {}

    totals = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS sales_taxable,
               COALESCE(SUM(cgst_amount+sgst_amount+igst_amount),0) AS output_gst
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type != 'credit_note'
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    outward = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst,
               COALESCE(SUM(cess_amount),0) AS cess
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('tax_invoice','debit_note')
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    itc = (await db.execute(text("""
        SELECT COALESCE(SUM(cgst_amount),0) AS cgst, COALESCE(SUM(sgst_amount),0) AS sgst,
               COALESCE(SUM(igst_amount),0) AS igst
        FROM purchase_orders WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    net = {k: max(0, float(outward[k]) - float(itc[k])) for k in ("cgst", "sgst", "igst")}

    b2b = (await db.execute(text("""
        SELECT invoice_no, invoice_date, billing_name, billing_gstin, taxable_amount, total_amount
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND billing_gstin IS NOT NULL AND billing_gstin != '' AND is_export = false
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    b2c = (await db.execute(text("""
        SELECT CASE WHEN supply_type='inter' AND total_amount>250000 THEN 'B2CL' ELSE 'B2CS' END AS category,
               COUNT(*) AS invoice_count, SUM(taxable_amount) AS taxable,
               SUM(cgst_amount+sgst_amount+igst_amount) AS total_tax
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND (billing_gstin IS NULL OR billing_gstin = '') AND is_export = false
        GROUP BY 1
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    cdnr = (await db.execute(text("""
        SELECT invoice_no, invoice_date, invoice_type, billing_name, taxable_amount, total_amount
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('credit_note','debit_note')
          AND billing_gstin IS NOT NULL AND billing_gstin != ''
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    exports = (await db.execute(text("""
        SELECT invoice_no, invoice_date, billing_name, export_type, taxable_amount
        FROM invoices WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    hsn = (await db.execute(text("""
        SELECT COALESCE(ii.hsn_code, ii.sac_code, 'N/A') AS hsn, MIN(ii.description) AS description,
               ii.gst_rate, SUM(ii.quantity) AS qty, SUM(ii.taxable_amount) AS taxable,
               SUM(ii.cgst_amount+ii.sgst_amount+ii.igst_amount) AS total_tax
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type != 'credit_note'
        GROUP BY COALESCE(ii.hsn_code, ii.sac_code, 'N/A'), ii.gst_rate ORDER BY taxable DESC
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    pdf_bytes = generate_report_pdf(
        title="GST Compliance Report",
        subtitle=f"Period: {month}",
        summary=[
            ("Sales (Taxable)", format_inr(totals["sales_taxable"]), "blue"),
            ("Output GST", format_inr(totals["output_gst"]), "green"),
            ("Input Tax Credit", format_inr(float(itc["cgst"]) + float(itc["sgst"]) + float(itc["igst"])), "orange"),
            ("Net Tax Payable", format_inr(net["cgst"] + net["sgst"] + net["igst"]), "red"),
        ],
        tables=[
            ("3.1 Outward Taxable Supplies", ["Taxable Value", "CGST", "SGST", "IGST", "Cess"],
             [[format_inr(outward["taxable"]), format_inr(outward["cgst"]), format_inr(outward["sgst"]),
               format_inr(outward["igst"]), format_inr(outward["cess"])]]),
            ("4. Eligible Input Tax Credit (ITC)", ["CGST", "SGST", "IGST"],
             [[format_inr(itc["cgst"]), format_inr(itc["sgst"]), format_inr(itc["igst"])]]),
            ("Net Tax Payable", ["CGST", "SGST", "IGST"],
             [[format_inr(net["cgst"]), format_inr(net["sgst"]), format_inr(net["igst"])]]),
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

@router.get("/gstr1/json", summary="Export GSTR-1 in GSTN Offline Utility JSON format")
async def gstr1_json_export(current: CurrentUserDep, db: DBDep, month: str = Query(...)) -> Response:
    cid = str(current.company_id)
    df, dt = _month_bounds(month)

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
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND billing_gstin IS NOT NULL AND billing_gstin != '' AND is_export = false
        ORDER BY billing_gstin, invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

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
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
          AND (billing_gstin IS NULL OR billing_gstin = '') AND is_export = false
        GROUP BY billing_state_code, supply_type
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

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
          AND status NOT IN ('draft','cancelled','void') AND invoice_type IN ('credit_note','debit_note')
          AND billing_gstin IS NOT NULL AND billing_gstin != ''
        ORDER BY billing_gstin, invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    cdnr_by_gstin: dict[str, list] = {}
    for r in cdnr_rows:
        cdnr_by_gstin.setdefault(r["billing_gstin"], []).append({
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
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice' AND is_export = true
        ORDER BY invoice_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    exp_by_type: dict[str, list] = {}
    for r in exp_rows:
        exp_by_type.setdefault(r["export_type"] or "WPAY", []).append({
            "inum": r["invoice_no"], "idt": _fmt_date(r["invoice_date"]),
            "val": float(r["total_amount"]), "sbpcode": "", "sbnum": "", "sbdt": "",
            "itms": [{"txval": float(r["taxable_amount"]), "iamt": float(r["igst_amount"])}],
        })
    exp = [{"exp_typ": t, "inv": invs} for t, invs in exp_by_type.items()]

    hsn_rows = (await db.execute(text("""
        SELECT COALESCE(ii.hsn_code, ii.sac_code, '') AS hsn, MIN(ii.description) AS desc,
               ii.gst_rate AS rt, SUM(ii.quantity) AS qty, SUM(ii.taxable_amount) AS txval,
               SUM(ii.cgst_amount) AS camt, SUM(ii.sgst_amount) AS samt, SUM(ii.igst_amount) AS iamt
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.company_id=:cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void') AND i.invoice_type != 'credit_note'
        GROUP BY COALESCE(ii.hsn_code, ii.sac_code, ''), ii.gst_rate
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

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