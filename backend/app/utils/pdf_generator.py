"""
VyaparPro — PDF Generation Engine
Generates print-ready PDFs for invoices, quotations, POs, delivery challans.
Uses ReportLab. Returns bytes for direct HTTP response or S3 upload.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.utils.gst_calculator import amount_in_words

# ── Brand colours ─────────────────────────────────────────────────────────────
BRAND_BLUE  = colors.HexColor("#0066CC")
BRAND_DARK  = colors.HexColor("#1A1A2E")
LIGHT_GREY  = colors.HexColor("#F5F5F5")
MED_GREY    = colors.HexColor("#CCCCCC")
TEXT_DARK   = colors.HexColor("#212121")


@dataclass
class PDFDocumentData:
    """All data needed to render any billing PDF."""
    doc_type: str           # invoice|quotation|po|delivery_challan|credit_note|debit_note
    doc_no: str
    doc_date: date
    due_date: Optional[date] = None
    # Seller
    company_name: str = ""
    company_gstin: str = ""
    company_address: str = ""
    company_phone: str = ""
    company_email: str = ""
    company_logo_url: Optional[str] = None
    # Buyer
    party_name: str = ""
    party_gstin: str = ""
    party_address: str = ""
    party_phone: str = ""
    party_email: str = ""
    # Optional references
    po_no: Optional[str] = None
    po_date: Optional[date] = None
    jo_no: Optional[str] = None
    place_of_supply: str = ""
    supply_type: str = "intra"
    # Line items
    items: list[dict] = field(default_factory=list)
    # Totals
    subtotal: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    taxable_amount: Decimal = Decimal("0")
    cgst_amount: Decimal = Decimal("0")
    sgst_amount: Decimal = Decimal("0")
    igst_amount: Decimal = Decimal("0")
    cess_amount: Decimal = Decimal("0")
    other_charges: Decimal = Decimal("0")
    tds_amount: Decimal = Decimal("0")
    round_off: Decimal = Decimal("0")
    total_amount: Decimal = Decimal("0")
    # IRN / E-invoice
    irn: Optional[str] = None
    ack_no: Optional[str] = None
    ack_date: Optional[datetime] = None
    qr_code_data: Optional[str] = None
    # Misc
    notes: str = ""
    terms_conditions: str = ""
    bank_name: str = ""
    bank_account_no: str = ""
    bank_ifsc: str = ""
    bank_branch: str = ""
    hsn_summary: list[dict] = field(default_factory=list)


def _fmt(v: Decimal | float, symbol: str = "₹") -> str:
    return f"{symbol}{float(v):,.2f}"


def generate_invoice_pdf(data: PDFDocumentData) -> bytes:
    """Generate a GST-compliant A4 tax invoice PDF. Returns raw bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, textColor=BRAND_BLUE, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=10, textColor=BRAND_DARK, spaceAfter=2)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=8, textColor=TEXT_DARK, leading=12)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7, textColor=colors.grey, leading=10)
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)
    center = ParagraphStyle("center", parent=body, alignment=TA_CENTER)
    bold8 = ParagraphStyle("bold8", parent=body, fontName="Helvetica-Bold")
    bold9 = ParagraphStyle("bold9", parent=body, fontSize=9, fontName="Helvetica-Bold")

    story = []

    # ── Header ────────────────────────────────────────────────────
    doc_label = {
        "invoice": "TAX INVOICE",
        "quotation": "QUOTATION",
        "po": "PURCHASE ORDER",
        "delivery_challan": "DELIVERY CHALLAN",
        "credit_note": "CREDIT NOTE",
        "debit_note": "DEBIT NOTE",
        "proforma": "PROFORMA INVOICE",
    }.get(data.doc_type, data.doc_type.upper().replace("_", " "))

    header_data = [
        [
            Paragraph(f"<b>{data.company_name}</b>", h2),
            Paragraph(f"<b>{doc_label}</b>", ParagraphStyle("doclabel", parent=h1, alignment=TA_RIGHT)),
        ],
        [
            Paragraph(data.company_address.replace("\n", "<br/>"), body),
            Table(
                [
                    [Paragraph("No:", bold8), Paragraph(data.doc_no, body)],
                    [Paragraph("Date:", bold8), Paragraph(str(data.doc_date), body)],
                    *([[Paragraph("Due:", bold8), Paragraph(str(data.due_date), body)]] if data.due_date else []),
                    *([[Paragraph("PO No:", bold8), Paragraph(data.po_no, body)]] if data.po_no else []),
                    *([[Paragraph("JO No:", bold8), Paragraph(data.jo_no, body)]] if data.jo_no else []),
                ],
                colWidths=[28 * mm, 48 * mm],
                style=TableStyle([("ALIGN", (0, 0), (-1, -1), "LEFT"), ("FONTSIZE", (0, 0), (-1, -1), 8)]),
            ),
        ],
        [
            Paragraph(f"GSTIN: {data.company_gstin}", small),
            Paragraph(f"Ph: {data.company_phone}  |  {data.company_email}", ParagraphStyle("sr", parent=small, alignment=TA_RIGHT)),
        ],
    ]
    header_table = Table(header_data, colWidths=[95 * mm, 88 * mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 2), (-1, 2), 0.5, BRAND_BLUE),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    # ── Billed To ─────────────────────────────────────────────────
    bt_data = [
        [Paragraph("<b>BILLED TO</b>", bold8), Paragraph("<b>PLACE OF SUPPLY</b>", bold8)],
        [Paragraph(f"<b>{data.party_name}</b>", body), Paragraph(data.place_of_supply, body)],
        [Paragraph(data.party_address.replace("\n", "<br/>"), body), Paragraph(f"Supply: {data.supply_type}", small)],
        [Paragraph(f"GSTIN: {data.party_gstin or 'Unregistered'}", small), ""],
    ]
    bt_table = Table(bt_data, colWidths=[130 * mm, 53 * mm])
    bt_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GREY),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, MED_GREY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, MED_GREY),
    ]))
    story.append(bt_table)
    story.append(Spacer(1, 4 * mm))

    # ── Items table ───────────────────────────────────────────────
    is_igst = data.igst_amount > 0
    if is_igst:
        col_headers = ["#", "Description", "HSN", "Qty", "Rate", "Disc", "Taxable", "GST%", "IGST", "Amount"]
        col_widths  = [8, 48, 14, 12, 18, 12, 18, 10, 16, 18]
    else:
        col_headers = ["#", "Description", "HSN", "Qty", "Rate", "Disc", "Taxable", "GST%", "CGST", "SGST", "Amount"]
        col_widths  = [8, 42, 12, 10, 16, 10, 18, 8, 14, 14, 18]
    col_widths = [w * mm for w in col_widths]

    item_rows = [col_headers]
    for item in data.items:
        if is_igst:
            row = [
                str(item.get("line_no", "")),
                item.get("description", ""),
                item.get("hsn_code", ""),
                str(item.get("quantity", "")),
                _fmt(item.get("rate", 0), ""),
                _fmt(item.get("discount_amount", 0), ""),
                _fmt(item.get("taxable_amount", 0), ""),
                f"{item.get('gst_rate', 0)}%",
                _fmt(item.get("igst_amount", 0), ""),
                _fmt(item.get("total_amount", 0), ""),
            ]
        else:
            row = [
                str(item.get("line_no", "")),
                item.get("description", ""),
                item.get("hsn_code", ""),
                str(item.get("quantity", "")),
                _fmt(item.get("rate", 0), ""),
                _fmt(item.get("discount_amount", 0), ""),
                _fmt(item.get("taxable_amount", 0), ""),
                f"{item.get('gst_rate', 0)}%",
                _fmt(item.get("cgst_amount", 0), ""),
                _fmt(item.get("sgst_amount", 0), ""),
                _fmt(item.get("total_amount", 0), ""),
            ]
        item_rows.append(row)

    items_table = Table(item_rows, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("GRID", (0, 0), (-1, -1), 0.4, MED_GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4 * mm))

    # ── Totals ────────────────────────────────────────────────────
    totals_rows = [
        ["Subtotal", _fmt(data.subtotal)],
        ["(-) Discount", _fmt(data.discount_amount)],
        ["Taxable Amount", _fmt(data.taxable_amount)],
    ]
    if is_igst:
        totals_rows.append(["IGST", _fmt(data.igst_amount)])
    else:
        totals_rows.append(["CGST", _fmt(data.cgst_amount)])
        totals_rows.append(["SGST", _fmt(data.sgst_amount)])
    if data.cess_amount:
        totals_rows.append(["CESS", _fmt(data.cess_amount)])
    if data.other_charges:
        totals_rows.append(["Other Charges", _fmt(data.other_charges)])
    if data.tds_amount:
        totals_rows.append(["(-) TDS", _fmt(data.tds_amount)])
    if data.round_off:
        totals_rows.append(["Round Off", _fmt(data.round_off)])
    totals_rows.append(["GRAND TOTAL", _fmt(data.total_amount)])

    totals_table = Table(
        totals_rows,
        colWidths=[80 * mm, 40 * mm],
        hAlign="RIGHT",
    )
    totals_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, BRAND_BLUE),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1), BRAND_BLUE),
        ("FONTSIZE", (0, -1), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 3 * mm))

    # Amount in words
    story.append(Paragraph(f"<b>Amount in Words:</b> {amount_in_words(data.total_amount)}", body))
    story.append(Spacer(1, 4 * mm))

    # ── HSN Summary ───────────────────────────────────────────────
    if data.hsn_summary:
        story.append(Paragraph("<b>HSN/SAC Summary</b>", bold8))
        hsn_rows = [["HSN/SAC", "Taxable Amt", "CGST", "SGST", "IGST", "CESS", "Total Tax"]]
        for h in data.hsn_summary:
            hsn_rows.append([
                h.get("hsn_code", ""),
                _fmt(h.get("taxable_amount", 0), ""),
                _fmt(h.get("cgst", 0), ""),
                _fmt(h.get("sgst", 0), ""),
                _fmt(h.get("igst", 0), ""),
                _fmt(h.get("cess", 0), ""),
                _fmt(h.get("total", 0) - float(h.get("taxable_amount", 0)), ""),
            ])
        hsn_table = Table(hsn_rows, colWidths=[20 * mm, 25 * mm, 20 * mm, 20 * mm, 20 * mm, 15 * mm, 22 * mm])
        hsn_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GREY),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.4, MED_GREY),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(hsn_table)
        story.append(Spacer(1, 4 * mm))

    # ── Bank + Notes + IRN ────────────────────────────────────────
    footer_left = []
    if data.bank_name:
        footer_left.append(Paragraph("<b>Bank Details:</b>", bold8))
        footer_left.append(Paragraph(f"{data.bank_name}  |  A/c: {data.bank_account_no}  |  IFSC: {data.bank_ifsc}", body))
        footer_left.append(Paragraph(f"Branch: {data.bank_branch}", body))
    if data.notes:
        footer_left.append(Spacer(1, 3 * mm))
        footer_left.append(Paragraph(f"<b>Notes:</b> {data.notes}", body))
    if data.terms_conditions:
        footer_left.append(Paragraph(f"<b>T&amp;C:</b> {data.terms_conditions}", small))

    footer_right = []
    if data.irn:
        footer_right.append(Paragraph(f"<b>IRN:</b> {data.irn}", small))
    if data.ack_no:
        footer_right.append(Paragraph(f"<b>Ack No:</b> {data.ack_no}", small))
    footer_right.append(Spacer(1, 8 * mm))
    footer_right.append(Paragraph(f"<b>For {data.company_name}</b>", bold8))
    footer_right.append(Spacer(1, 10 * mm))
    footer_right.append(Paragraph("Authorised Signatory", small))

    from reportlab.platypus import KeepTogether
    footer_table = Table(
        [[footer_left, footer_right]],
        colWidths=[110 * mm, 73 * mm],
    )
    footer_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_GREY))
    story.append(Spacer(1, 3 * mm))
    story.append(footer_table)

    # ── Build ─────────────────────────────────────────────────────
    doc.build(story)
    buffer.seek(0)
    return buffer.read()
