"""VyaparPro — Reports & Analytics (read-only aggregation endpoints)"""
from __future__ import annotations
from datetime import date, timedelta
from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse
from sqlalchemy import text
from fastapi import Response
from app.utils.pdf_generator import generate_report_pdf

from app.api.v1.dependencies import CurrentUserDep, DBDep
from app.utils.responses import ok
import uuid
from decimal import Decimal
from app.utils.pdf_generator import generate_report_pdf, format_inr

def _clean(obj):
    """Recursively convert Decimal -> float, date -> isoformat, UUID -> str for JSON serialization."""
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

router = APIRouter()


@router.get("/sales", summary="Sales report — revenue by customer & product",response_model=None)
async def sales_report(
    current: CurrentUserDep, db: DBDep,
    date_from: date = Query(default_factory=lambda: date.today().replace(day=1)),
    date_to: date = Query(default_factory=date.today),
    as_pdf: bool = Query(False),
) -> ORJSONResponse | Response:
    cid = str(current.company_id)

    summary = (await db.execute(text("""
        SELECT COUNT(*) AS invoice_count,
               COALESCE(SUM(total_amount) FILTER (WHERE invoice_type != 'credit_note'), 0)
               - COALESCE(SUM(total_amount) FILTER (WHERE invoice_type = 'credit_note'), 0) AS total_revenue,
               COALESCE(SUM(cgst_amount + sgst_amount + igst_amount), 0) AS total_tax
        FROM invoices
        WHERE company_id = :cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void')
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().one()

    by_customer = (await db.execute(text("""
        SELECT COALESCE(i.party_id::text, lower(trim(i.billing_name))) AS customer_key,
               MAX(i.party_id::text) AS party_id,
               COALESCE(MAX(p.display_name), MIN(i.billing_name)) AS customer_name,
               COUNT(*) FILTER (WHERE i.invoice_type NOT IN ('credit_note','debit_note')) AS invoice_count,
               COALESCE(SUM(i.total_amount) FILTER (WHERE i.invoice_type != 'credit_note'), 0)
                 - COALESCE(SUM(i.total_amount) FILTER (WHERE i.invoice_type = 'credit_note'), 0) AS total
        FROM invoices i LEFT JOIN parties p ON p.id = i.party_id
        WHERE i.company_id = :cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void')
        GROUP BY COALESCE(i.party_id::text, lower(trim(i.billing_name)))
        HAVING COUNT(*) FILTER (WHERE i.invoice_type NOT IN ('credit_note','debit_note')) > 0
        ORDER BY total DESC LIMIT 500
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().all()

    by_product = (await db.execute(text("""
        SELECT COALESCE(ii.product_id::text, lower(trim(ii.description))) AS product_key,
               MAX(ii.product_id::text) AS product_id,
               COALESCE(MAX(p.product_name), MIN(ii.description)) AS product_name,
               SUM(ii.quantity) AS qty_sold, SUM(ii.taxable_amount) AS revenue
        FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
        LEFT JOIN products p ON p.id = ii.product_id
        WHERE i.company_id = :cid AND i.invoice_date BETWEEN :df AND :dt
          AND i.status NOT IN ('draft','cancelled','void')
          AND i.invoice_type NOT IN ('credit_note','debit_note')
        GROUP BY COALESCE(ii.product_id::text, lower(trim(ii.description)))
        ORDER BY revenue DESC
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().all()

    sales_summary = (await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE invoice_type != 'credit_note') AS invoice_count,
               COALESCE(AVG(total_amount) FILTER (WHERE invoice_type != 'credit_note'), 0) AS avg_invoice,
               COALESCE(MAX(total_amount) FILTER (WHERE invoice_type != 'credit_note'), 0) AS highest_invoice,
               COALESCE(MIN(total_amount) FILTER (WHERE invoice_type != 'credit_note' AND total_amount > 0), 0) AS lowest_invoice,
               COALESCE(SUM(total_amount) FILTER (WHERE invoice_type = 'credit_note'), 0) AS sales_returns,
               COALESCE(SUM(paid_amount) FILTER (WHERE invoice_type != 'credit_note'), 0) AS collected,
               COALESCE(SUM(total_amount - paid_amount) FILTER (WHERE invoice_type != 'credit_note' AND status NOT IN ('paid','cancelled','void','draft')), 0) AS outstanding
        FROM invoices
        WHERE company_id = :cid AND invoice_date BETWEEN :df AND :dt AND status NOT IN ('draft','cancelled','void')
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().one()

    gst_summary = (await db.execute(text("""
        SELECT COALESCE(SUM(taxable_amount),0) AS taxable, COALESCE(SUM(cgst_amount),0) AS cgst,
               COALESCE(SUM(sgst_amount),0) AS sgst, COALESCE(SUM(igst_amount),0) AS igst,
               COALESCE(SUM(cess_amount),0) AS cess
        FROM invoices
        WHERE company_id = :cid AND invoice_date BETWEEN :df AND :dt
          AND status NOT IN ('draft','cancelled','void') AND invoice_type != 'credit_note'
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().one()

    if as_pdf:
        company_row = (await db.execute(
            text("SELECT legal_name, reg_address, gstin, phone, email, website FROM companies WHERE id = :cid"),
            {"cid": cid}
        )).mappings().one_or_none() or {}
        pdf_bytes = generate_report_pdf(
            title="Sales Report",
            subtitle=f"{date_from} to {date_to}",
            summary=[
                ("Total Invoices", str(summary["invoice_count"]), "blue"),
                ("Total Revenue", format_inr(summary["total_revenue"]), "green"),
                ("Tax Collected", format_inr(summary["total_tax"]), "orange"),
            ],
            bar_chart={
                "title": "Top Customers by Revenue",
                "categories": [c["customer_name"] or "—" for c in by_customer[:8]],
                "values": [float(c["total"]) for c in by_customer[:8]],
            },
            tables=[
                ("Top Customers", ["Customer","Invoices","Total"],
                 [[c["customer_name"] or "—", str(c["invoice_count"]), format_inr(c["total"])] for c in by_customer]),
                ("Top Products", ["Product","Qty Sold","Revenue"],
                 [[p["product_name"] or "—", f"{float(p['qty_sold']):.0f}", format_inr(p["revenue"])] for p in by_product]),
                ("Sales Summary", ["Metric","Value"], [
                    ["Average Invoice Value", format_inr(sales_summary["avg_invoice"])],
                    ["Highest Invoice", format_inr(sales_summary["highest_invoice"])],
                    ["Lowest Invoice", format_inr(sales_summary["lowest_invoice"])],
                    ["Sales Returns", format_inr(sales_summary["sales_returns"])],
                    ["Net Sales", format_inr(float(summary["total_revenue"]) - float(sales_summary["sales_returns"]))],
                    ["Collected Amount", format_inr(sales_summary["collected"])],
                    ["Outstanding Receivables", format_inr(sales_summary["outstanding"])],
                ]),
                ("GST Summary", ["Component","Amount"], [
                    ["Taxable Value", format_inr(gst_summary["taxable"])],
                    ["CGST", format_inr(gst_summary["cgst"])],
                    ["SGST", format_inr(gst_summary["sgst"])],
                    ["IGST", format_inr(gst_summary["igst"])],
                    ["CESS", format_inr(gst_summary["cess"])],
                ]),
            ],
            company=dict(company_row),
            period=f"{date_from} to {date_to}",
            generated_by=current.full_name if hasattr(current, "full_name") else "System",
        )
        return Response(content=pdf_bytes, media_type="application/pdf",
                         headers={"Content-Disposition": f'attachment; filename="sales_report_{date_from}_{date_to}.pdf"'})

    return ok(data=_clean({
        "summary": dict(summary),
        "sales_summary": dict(sales_summary),
        "gst_summary": dict(gst_summary),
        "by_customer": [dict(r) for r in by_customer],
        "by_product": [dict(r) for r in by_product],
        "period": {"date_from": date_from, "date_to": date_to},
    }))


@router.get("/purchases", summary="Purchase report — spend by vendor & product",response_model=None)
async def purchase_report(
    current: CurrentUserDep, db: DBDep,
    date_from: date = Query(default_factory=lambda: date.today().replace(day=1)),
    date_to: date = Query(default_factory=date.today),
    as_pdf: bool = Query(False),
) -> ORJSONResponse | Response:
    cid = str(current.company_id)

    summary = (await db.execute(text("""
        SELECT COUNT(*) AS po_count, COALESCE(SUM(total_amount), 0) AS total_purchases,
               COALESCE(SUM(total_amount - paid_amount), 0) AS total_payable
        FROM purchase_orders
        WHERE company_id = :cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().one()

    by_vendor = (await db.execute(text("""
        SELECT po.vendor_id, COALESCE(p.display_name, 'Unknown') AS vendor_name,
               COUNT(*) AS po_count, SUM(po.total_amount) AS total
        FROM purchase_orders po LEFT JOIN parties p ON p.id = po.vendor_id
        WHERE po.company_id = :cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
        GROUP BY po.vendor_id, p.display_name
        ORDER BY total DESC LIMIT 500
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().all()

    by_product = (await db.execute(text("""
        SELECT poi.product_id, poi.description AS product_name,
               SUM(poi.quantity) AS qty_purchased, SUM(poi.amount) AS amount
        FROM purchase_order_items poi JOIN purchase_orders po ON po.id = poi.po_id
        WHERE po.company_id = :cid AND po.po_date BETWEEN :df AND :dt AND po.status != 'cancelled'
        GROUP BY poi.product_id, poi.description
        ORDER BY amount DESC LIMIT 500
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().all()

    po_summary = (await db.execute(text("""
        SELECT COALESCE(AVG(total_amount),0) AS avg_po, COALESCE(MAX(total_amount),0) AS highest_po,
               COALESCE(SUM(paid_amount),0) AS paid, COALESCE(SUM(total_amount - paid_amount),0) AS outstanding
        FROM purchase_orders WHERE company_id = :cid AND po_date BETWEEN :df AND :dt AND status != 'cancelled'
    """), {"cid": cid, "df": date_from, "dt": date_to})).mappings().one()

    if as_pdf:
        company_row = (await db.execute(
            text("SELECT legal_name, reg_address, gstin, phone, email, website FROM companies WHERE id = :cid"),
            {"cid": cid}
        )).mappings().one_or_none() or {}
        pdf_bytes = generate_report_pdf(
            title="Purchase Report",
            subtitle=f"{date_from} to {date_to}",
            summary=[
                ("Purchase Orders", str(summary["po_count"]), "blue"),
                ("Total Purchases", format_inr(summary["total_purchases"]), "orange"),
                ("Payable", format_inr(summary["total_payable"]), "red"),
            ],
            bar_chart={
                "title": "Top Vendors by Spend",
                "categories": [v["vendor_name"] or "—" for v in by_vendor[:8]],
                "values": [float(v["total"]) for v in by_vendor[:8]],
            },
            tables=[
                ("Top Vendors", ["Vendor","POs","Total"],
                 [[v["vendor_name"] or "—", str(v["po_count"]), format_inr(v["total"])] for v in by_vendor]),
                ("Top Products Purchased", ["Product","Qty","Amount"],
                 [[p["product_name"] or "—", f"{float(p['qty_purchased']):.0f}", format_inr(p["amount"])] for p in by_product]),
                ("Purchase Summary", ["Metric","Value"], [
                    ["Average Purchase", format_inr(po_summary["avg_po"])],
                    ["Highest Purchase", format_inr(po_summary["highest_po"])],
                    ["Paid Amount", format_inr(po_summary["paid"])],
                    ["Pending Payables", format_inr(po_summary["outstanding"])],
                ]),
            ],
            company=dict(company_row),
            period=f"{date_from} to {date_to}",
            generated_by=current.full_name if hasattr(current, "full_name") else "System",
        )
        return Response(content=pdf_bytes, media_type="application/pdf",
                         headers={"Content-Disposition": f'attachment; filename="purchase_report_{date_from}_{date_to}.pdf"'})

    return ok(data=_clean({
        "summary": dict(summary),
        "po_summary": dict(po_summary),
        "by_vendor": [dict(r) for r in by_vendor],
        "by_product": [dict(r) for r in by_product],
        "period": {"date_from": date_from, "date_to": date_to},
    }))


@router.get("/inventory", summary="Inventory report — stock valuation & reorder alerts", response_model=None)
async def inventory_report(current: CurrentUserDep, db: DBDep, as_pdf: bool = Query(False)) -> ORJSONResponse | Response:
    cid = str(current.company_id)

    summary = (await db.execute(text("""
        SELECT COUNT(*) AS total_products,
               COALESCE(SUM(current_stock * purchase_price), 0) AS stock_value,
               COUNT(*) FILTER (WHERE current_stock <= reorder_level AND current_stock > 0) AS low_stock_count,
               COUNT(*) FILTER (WHERE current_stock <= 0) AS out_of_stock_count
        FROM products
        WHERE company_id = :cid AND is_active = true AND is_service = false
    """), {"cid": cid})).mappings().one()

    items = (await db.execute(text("""
        SELECT id, product_name, product_code, current_stock, reorder_level,
               purchase_price, (current_stock * purchase_price) AS stock_value,
               CASE WHEN current_stock <= 0 THEN 'Out of Stock'
                    WHEN current_stock <= reorder_level THEN 'Low Stock'
                    ELSE 'OK' END AS stock_status
        FROM products
        WHERE company_id = :cid AND is_active = true AND is_service = false
        ORDER BY (current_stock <= reorder_level) DESC, stock_value DESC
        LIMIT 2000
    """), {"cid": cid})).mappings().all()

    if as_pdf:
        company_row = (await db.execute(
            text("SELECT legal_name, reg_address, gstin, phone, email, website FROM companies WHERE id = :cid"),
            {"cid": cid}
        )).mappings().one_or_none() or {}
        status_counts = {"OK": 0, "Low Stock": 0, "Out of Stock": 0}
        for i in items:
            status_counts[i["stock_status"]] = status_counts.get(i["stock_status"], 0) + 1
        pdf_bytes = generate_report_pdf(
            title="Inventory Report",
            subtitle=f"As of {date.today()}",
            summary=[
                ("Total Products", str(summary["total_products"]), "blue"),
                ("Stock Value", format_inr(summary["stock_value"]), "green"),
                ("Low Stock", str(summary["low_stock_count"]), "orange"),
                ("Out of Stock", str(summary["out_of_stock_count"]), "red"),
            ],
            pie_chart={"labels": list(status_counts.keys()), "values": list(status_counts.values())},
            tables=[
                ("Stock Detail", ["Product","Code","Stock","Reorder Level","Value","Status"],
                 [[i["product_name"], i["product_code"], str(i["current_stock"]), str(i["reorder_level"]),
                   format_inr(i["stock_value"]), i["stock_status"]] for i in items]),
            ],
            company=dict(company_row),
            generated_by=current.full_name if hasattr(current, "full_name") else "System",
        )
        return Response(content=pdf_bytes, media_type="application/pdf",
                         headers={"Content-Disposition": f'attachment; filename="inventory_report_{date.today()}.pdf"'})

    return ok(data=_clean({"summary": dict(summary), "items": [dict(r) for r in items]}))


@router.get("/customers", summary="Customer report — outstanding, LTV, activity",response_model=None)
async def customer_report(current: CurrentUserDep, db: DBDep, as_pdf: bool = Query(False)) -> ORJSONResponse | Response:
    cid = str(current.company_id)

    rows = (await db.execute(text("""
        SELECT p.id, p.display_name AS name, p.billing_city AS city,
               COALESCE(SUM(i.total_amount) FILTER (WHERE i.invoice_type != 'credit_note'), 0) AS total_business,
               COALESCE(SUM(i.total_amount - i.paid_amount) FILTER (
                   WHERE i.status NOT IN ('paid','cancelled','void','draft') AND i.invoice_type != 'credit_note'
               ), 0) AS outstanding,
               MAX(i.invoice_date) AS last_purchase, COUNT(i.id) AS invoice_count
        FROM parties p LEFT JOIN invoices i ON i.party_id = p.id AND i.status NOT IN ('cancelled','void','draft')
        WHERE p.company_id = :cid AND p.party_type = 'customer' AND p.is_active = true
        GROUP BY p.id, p.display_name, p.billing_city
        ORDER BY total_business DESC LIMIT 500
    """), {"cid": cid})).mappings().all()

    summary = {
        "total_customers": len(rows),
        "total_outstanding": sum(float(r["outstanding"] or 0) for r in rows),
        "total_revenue": sum(float(r["total_business"] or 0) for r in rows),
    }
    cust_summary = (await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE p.is_active) AS active_customers,
               COUNT(*) FILTER (WHERE NOT p.is_active) AS inactive_customers,
               COUNT(*) FILTER (WHERE p.created_at >= CURRENT_DATE - INTERVAL '30 days') AS new_customers,
               COUNT(DISTINCT i.party_id) FILTER (WHERE i.invoice_date >= CURRENT_DATE - INTERVAL '90 days') AS repeat_customers
        FROM parties p LEFT JOIN invoices i ON i.party_id = p.id
        WHERE p.company_id = :cid AND p.party_type = 'customer'
    """), {"cid": cid})).mappings().one()

    aging = (await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE CURRENT_DATE - due_date BETWEEN 0 AND 30) AS b0_30,
               SUM(total_amount - paid_amount) FILTER (WHERE CURRENT_DATE - due_date BETWEEN 0 AND 30) AS a0_30,
               COUNT(*) FILTER (WHERE CURRENT_DATE - due_date BETWEEN 31 AND 60) AS b31_60,
               SUM(total_amount - paid_amount) FILTER (WHERE CURRENT_DATE - due_date BETWEEN 31 AND 60) AS a31_60,
               COUNT(*) FILTER (WHERE CURRENT_DATE - due_date BETWEEN 61 AND 90) AS b61_90,
               SUM(total_amount - paid_amount) FILTER (WHERE CURRENT_DATE - due_date BETWEEN 61 AND 90) AS a61_90,
               COUNT(*) FILTER (WHERE CURRENT_DATE - due_date > 90) AS b90plus,
               SUM(total_amount - paid_amount) FILTER (WHERE CURRENT_DATE - due_date > 90) AS a90plus
        FROM invoices
        WHERE company_id = :cid AND status NOT IN ('paid','cancelled','void','draft') AND invoice_type != 'credit_note'
    """), {"cid": cid})).mappings().one()

    if as_pdf:
        company_row = (await db.execute(
            text("SELECT legal_name, reg_address, gstin, phone, email, website FROM companies WHERE id = :cid"),
            {"cid": cid}
        )).mappings().one_or_none() or {}
        pdf_bytes = generate_report_pdf(
            title="Customer Report",
            subtitle=f"As of {date.today()}",
            summary=[
                ("Total Customers", str(summary["total_customers"]), "blue"),
                ("Total Revenue", format_inr(summary["total_revenue"]), "green"),
                ("Total Outstanding", format_inr(summary["total_outstanding"]), "red"),
            ],
            bar_chart={
                "title": "Top Customers by Business",
                "categories": [r["name"] for r in rows[:8]],
                "values": [float(r["total_business"]) for r in rows[:8]],
            },
            tables=[
                ("Customer Breakdown", ["Customer","City","Invoices","Total Business","Outstanding","Last Purchase"],
                 [[r["name"], r["city"] or "—", str(r["invoice_count"]), format_inr(r["total_business"]),
                   format_inr(r["outstanding"]), str(r["last_purchase"] or "—")] for r in rows]),
                ("Customer Summary", ["Metric","Value"], [
                    ["Active Customers", str(cust_summary["active_customers"])],
                    ["Inactive Customers", str(cust_summary["inactive_customers"])],
                    ["New Customers (30d)", str(cust_summary["new_customers"])],
                    ["Repeat Customers (90d)", str(cust_summary["repeat_customers"])],
                ]),
                ("Outstanding Aging Analysis", ["Bucket","Invoices","Amount"], [
                    ["0-30 days", str(aging["b0_30"] or 0), format_inr(aging["a0_30"])],
                    ["31-60 days", str(aging["b31_60"] or 0), format_inr(aging["a31_60"])],
                    ["61-90 days", str(aging["b61_90"] or 0), format_inr(aging["a61_90"])],
                    ["90+ days", str(aging["b90plus"] or 0), format_inr(aging["a90plus"])],
                ]),
            ],
            company = dict(company_row),
            period=f"As of {date.today()}",
            generated_by=current.full_name if hasattr(current, "full_name") else "System",
        )
 
        return Response(content=pdf_bytes, media_type="application/pdf",
                         headers={"Content-Disposition": f'attachment; filename="customer_report_{date.today()}.pdf"'})

    return ok(data=_clean({
        "summary": summary,
        "customer_summary": dict(cust_summary),
        "aging": dict(aging),
        "customers": [dict(r) for r in rows],
    }))


@router.get("/{report_type}/pdf", summary="Download a report as PDF")
async def download_report_pdf(
    report_type: str, current: CurrentUserDep, db: DBDep,
    date_from: date = Query(default_factory=lambda: date.today().replace(day=1)),
    date_to: date = Query(default_factory=date.today),
) -> Response:
    company_name = (await db.execute(
        text("SELECT legal_name FROM companies WHERE id = :cid"), {"cid": str(current.company_id)}
    )).scalar() or ""

    if report_type == "sales":
        r = await sales_report(current, db, date_from, date_to)
        d = r.body  # not usable directly; call the underlying data instead — see note below
    raise NotImplementedError