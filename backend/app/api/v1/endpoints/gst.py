"""VyaparPro — GST Compliance Reports (live-computed, read-only)"""
from __future__ import annotations
from datetime import date
import calendar
from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse
from sqlalchemy import text

from app.api.v1.dependencies import CurrentUserDep, DBDep
from app.utils.responses import ok
from datetime import datetime as dt_now
from app.db.models.accounting import GSTReturn

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
          AND status NOT IN ('draft','cancelled','void') AND invoice_type != 'credit_note'
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    itc = (await db.execute(text("""
        SELECT COALESCE(SUM(cgst_amount+sgst_amount+igst_amount),0) AS input_tax_credit
        FROM purchase_orders WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
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

    outward = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable,
               COALESCE(SUM(cgst_amount),0) AS cgst, COALESCE(SUM(sgst_amount),0) AS sgst,
               COALESCE(SUM(igst_amount),0) AS igst, COALESCE(SUM(cess_amount),0) AS cess
        FROM invoices
        WHERE company_id=:cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type = 'tax_invoice'
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    itc_available = (await db.execute(text("""
        SELECT COALESCE(SUM(cgst_amount),0) AS cgst, COALESCE(SUM(sgst_amount),0) AS sgst,
               COALESCE(SUM(igst_amount),0) AS igst
        FROM purchase_orders WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    net_payable = {
        "cgst": max(0, float(outward["cgst"]) - float(itc_available["cgst"])),
        "sgst": max(0, float(outward["sgst"]) - float(itc_available["sgst"])),
        "igst": max(0, float(outward["igst"]) - float(itc_available["igst"])),
    }

    return ok(data=_clean({
        "outward_taxable_supplies": dict(outward),
        "itc_available": dict(itc_available),
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
               po.taxable_amount, po.cgst_amount, po.sgst_amount, po.igst_amount,
               po.cgst_amount+po.sgst_amount+po.igst_amount AS total_itc
        FROM purchase_orders po LEFT JOIN parties p ON p.id = po.vendor_id
        WHERE po.company_id=:cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
        ORDER BY po.po_date
    """), {"cid": cid, "df": df, "dt": dt})).mappings().all()

    totals = (await db.execute(text("""
        SELECT COALESCE(SUM(cgst_amount),0) AS cgst, COALESCE(SUM(sgst_amount),0) AS sgst,
               COALESCE(SUM(igst_amount),0) AS igst,
               COALESCE(SUM(cgst_amount+sgst_amount+igst_amount),0) AS total
        FROM purchase_orders WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
    """), {"cid": cid, "df": df, "dt": dt})).mappings().one()

    return ok(data=_clean({
        "totals": dict(totals),
        "by_vendor": [dict(r) for r in by_vendor],
        "note": "Shows ITC available from this period's purchases. Utilization tracking against actual filed GSTR-3B returns is not yet implemented.",
    }))



def _compute_setoff(output: dict, itc: dict) -> dict:
    igst_credit, cgst_credit, sgst_credit = float(itc["igst"]), float(itc["cgst"]), float(itc["sgst"])
    igst_liab, cgst_liab, sgst_liab = float(output["igst"]), float(output["cgst"]), float(output["sgst"])

    use = min(igst_liab, igst_credit); igst_liab -= use; igst_credit -= use
    use = min(igst_liab, cgst_credit); igst_liab -= use; cgst_credit -= use
    use = min(igst_liab, sgst_credit); igst_liab -= use; sgst_credit -= use

    use = min(cgst_liab, cgst_credit); cgst_liab -= use; cgst_credit -= use
    use = min(cgst_liab, igst_credit); cgst_liab -= use; igst_credit -= use

    use = min(sgst_liab, sgst_credit); sgst_liab -= use; sgst_credit -= use
    use = min(sgst_liab, igst_credit); sgst_liab -= use; igst_credit -= use

    return {"net_cgst": round(cgst_liab, 2), "net_sgst": round(sgst_liab, 2), "net_igst": round(igst_liab, 2),
            "remaining_itc": {"cgst": round(cgst_credit, 2), "sgst": round(sgst_credit, 2), "igst": round(igst_credit, 2)}}


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
    """), {"cid": str(cid), "df": df, "dt": dt})).mappings().one()

    itc = (await db.execute(text("""
        SELECT COALESCE(SUM(cgst_amount),0) AS cgst, COALESCE(SUM(sgst_amount),0) AS sgst,
               COALESCE(SUM(igst_amount),0) AS igst
        FROM purchase_orders WHERE company_id=:cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
    """), {"cid": str(cid), "df": df, "dt": dt})).mappings().one()

    setoff = _compute_setoff(dict(outward), dict(itc))
    total_payable = setoff["net_cgst"] + setoff["net_sgst"] + setoff["net_igst"]

    gst_return = GSTReturn(
        company_id=cid, return_type="GSTR-3B", period_from=df, period_to=dt,
        financial_year=f"{df.year}-{str(df.year+1)[2:]}" if df.month >= 4 else f"{df.year-1}-{str(df.year)[2:]}",
        taxable_turnover=outward["taxable"],
        total_cgst_output=outward["cgst"], total_sgst_output=outward["sgst"], total_igst_output=outward["igst"],
        itc_cgst=itc["cgst"], itc_sgst=itc["sgst"], itc_igst=itc["igst"],
        net_cgst_payable=setoff["net_cgst"], net_sgst_payable=setoff["net_sgst"], net_igst_payable=setoff["net_igst"],
        total_tax_payable=total_payable, status="filed", filed_at=dt_now.utcnow(), filed_by=current.user_id,
    )
    db.add(gst_return)
    await db.flush()

    return ok(data=_clean({
        "status": "filed", "filed_at": gst_return.filed_at, "net_payable": setoff,
        "remaining_itc": setoff["remaining_itc"],
    }), message=f"GSTR-3B filed for {month}.")


@router.get("/filed-returns", summary="History of filed GST returns")
async def filed_returns(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    rows = (await db.execute(text("""
        SELECT return_type, period_from, period_to, taxable_turnover, total_tax_payable,
               net_cgst_payable, net_sgst_payable, net_igst_payable, status, filed_at, arn
        FROM gst_returns WHERE company_id=:cid ORDER BY period_from DESC
    """), {"cid": str(current.company_id)})).mappings().all()
    return ok(data=_clean({"returns": [dict(r) for r in rows]}))