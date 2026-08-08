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
    HRFlowable, Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
import os

from app.utils.gst_calculator import amount_in_words
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("NotoSans", "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("NotoSans-Bold", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"))
    FONT_REGULAR = "NotoSans"
    FONT_BOLD = "NotoSans-Bold"
except Exception:
    pass

# ── Brand colours ─────────────────────────────────────────────────────────────
BRAND_BLUE  = colors.HexColor("#0066CC")
BRAND_DARK  = colors.HexColor("#1A1A2E")
BRAND_ACCENT = colors.HexColor("#00C2A8")
BG_SOFT      = colors.HexColor("#F0F4FA")
GOOD_GREEN   = colors.HexColor("#0E9F6E")
WARN_ORANGE  = colors.HexColor("#E8720C")
BAD_RED      = colors.HexColor("#DC2626")
LIGHT_GREY  = colors.HexColor("#F5F5F5")
MED_GREY    = colors.HexColor("#CCCCCC")
TEXT_DARK   = colors.HexColor("#212121")

GST_STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli", "27": "Maharashtra", "28": "Andhra Pradesh (Old)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}

def _state_label(code: str) -> str:
    code = (code or "").strip()
    name = GST_STATE_CODES.get(code.zfill(2))
    return f"{code} - {name}" if name else (code or "-")


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
    company_tagline: str = ""
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
    # Purchase-order-specific
    expected_delivery: Optional[date] = None
    delivery_address: str = ""
    buyer_contact: str = ""
    supplier_ref: str = ""
    payment_terms: str = ""
    delivery_terms: str = ""
    remarks: str = ""
    status: str = ""  # 'paid' | 'unpaid' | 'overdue' | 'draft' etc — drives the status badge
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
    company_pan: str = ""
    eway_bill_no: str = ""
    transporter_name: str = ""
    transporter_id: str = ""
    vehicle_no: str = ""
    challan_no: str = ""
    challan_date: Optional[date] = None
    upi_id: str = ""
    copy_label: str = "ORIGINAL FOR RECIPIENT"


def _fmt(v) -> str:
    """Indian numbering, currency symbol only if the loaded font can render it: ₹17,84,963.00 / Rs.17,84,963.00"""
    v = float(v or 0)
    neg = v < 0
    v = abs(v)
    whole, _, frac = f"{v:,.2f}".partition(".")
    whole = whole.replace(",", "")
    if len(whole) > 3:
        last3, rest = whole[-3:], whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        whole = ",".join(groups) + "," + last3
    symbol = "\u20b9" if FONT_REGULAR == "NotoSans" else "Rs."
    sep = "" if symbol == "\u20b9" else "\u00a0"
    return f"{'-' if neg else ''}{symbol}{sep}{whole}.{frac}"

def _fmt_compact(v) -> str:
    """Same formatting as _fmt but without the Rs./₹ prefix — for dense table
    cells where the column header already implies currency and every extra
    character eats into already-tight column width."""
    s = _fmt(v)
    return s.replace("\u20b9", "").replace("Rs.\u00a0", "").replace("Rs.", "").strip()

def _footer(canvas, doc):
    canvas.saveState()
    page_w, _ = A4
    canvas.setFillColor(colors.HexColor("#999999"))
    canvas.setFont(FONT_REGULAR, 7)
    canvas.drawString(12*mm, 8*mm, "Generated by VyaparPro ERP · Confidential")
    canvas.drawRightString(page_w - 12*mm, 8*mm, f"Page {doc.page}")
    canvas.restoreState()


from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF


def _qr_drawing(data: str, size: float = 26*mm) -> Drawing:
    qr = QrCodeWidget(data)
    b = qr.getBounds()
    w, h = b[2]-b[0], b[3]-b[1]
    d = Drawing(size, size, transform=[size/w, 0, 0, size/h, 0, 0])
    d.add(qr)
    return d


def generate_invoice_pdf(data: PDFDocumentData) -> bytes:
    """Classic bordered-grid GST tax invoice — matches standard Indian invoicing format."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=8*mm, leftMargin=8*mm,
                             topMargin=8*mm, bottomMargin=8*mm)
    styles = getSampleStyleSheet()
    BORDER = colors.black
    THIN = 0.6
    THICK = 1.2

    h_company = ParagraphStyle("hco", fontName=FONT_BOLD, fontSize=21, textColor=BRAND_DARK, leading=24)
    h_tagline = ParagraphStyle("htag", fontName=FONT_BOLD, fontSize=9.5, textColor=colors.white, alignment=TA_CENTER)
    contact = ParagraphStyle("contact", fontName=FONT_REGULAR, fontSize=8, textColor=TEXT_DARK, leading=11)
    contact_r = ParagraphStyle("contactr", parent=contact, alignment=TA_RIGHT)
    doclabel = ParagraphStyle("doclabel", fontName=FONT_BOLD, fontSize=18, alignment=TA_CENTER, leading=22)
    label8 = ParagraphStyle("label8", fontName=FONT_BOLD, fontSize=8)
    body8 = ParagraphStyle("body8", fontName=FONT_REGULAR, fontSize=8, leading=11)
    section_hdr = ParagraphStyle("sechdr", fontName=FONT_BOLD, fontSize=8, alignment=TA_CENTER)
    small = ParagraphStyle("small", fontName=FONT_REGULAR, fontSize=7)

    cell_l = ParagraphStyle("celll", fontName=FONT_REGULAR, fontSize=7, alignment=TA_LEFT, leading=8.5)
    cell_c = ParagraphStyle("cellc", fontName=FONT_REGULAR, fontSize=7, alignment=TA_CENTER, leading=8.5)
    cell_r = ParagraphStyle("cellr", fontName=FONT_REGULAR, fontSize=7, alignment=TA_RIGHT, leading=8.5)
    tot_bold_l = ParagraphStyle("totboldl", fontName=FONT_BOLD, fontSize=7, alignment=TA_LEFT)
    tot_bold_c = ParagraphStyle("totboldc", fontName=FONT_BOLD, fontSize=7, alignment=TA_CENTER)
    tot_bold_r = ParagraphStyle("totboldr", fontName=FONT_BOLD, fontSize=7, alignment=TA_RIGHT)

    def P(v, style=cell_r):
        return Paragraph(str(v) if v not in (None, "") else "-", style)

    doc_label = {
        "invoice": "TAX INVOICE", "quotation": "QUOTATION", "po": "PURCHASE ORDER",
        "delivery_challan": "DELIVERY CHALLAN", "credit_note": "CREDIT NOTE",
        "debit_note": "DEBIT NOTE", "proforma": "PROFORMA INVOICE",
        "purchase_return": "PURCHASE RETURN / DEBIT NOTE",
    }.get(data.doc_type, data.doc_type.upper().replace("_", " "))

    story = []

    # -- Company header band (now boxed to match the bordered sections below) --
    logo_flowable = ""
    if data.company_logo_url:
        logo_path = ("app" + data.company_logo_url) if data.company_logo_url.startswith("/static/") else data.company_logo_url
        if os.path.exists(logo_path):
            try:
                from PIL import Image as PILImage
                with PILImage.open(logo_path) as im:
                    iw, ih = im.size
                max_dim = 20 * mm
                scale = max_dim / max(iw, ih)
                logo_flowable = RLImage(logo_path, width=iw * scale, height=ih * scale)
            except Exception:
                logo_flowable = ""

    header_inner = Table([[logo_flowable, Paragraph(f"<b>{data.company_name or 'Company Name'}</b>", h_company)]],
                          colWidths=[24*mm, 154*mm])
    header_inner.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("ALIGN",(0,0),(0,0),"CENTER"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))

    addr_row = Table([[
        Paragraph((data.company_address or "").replace("\n", "<br/>"), contact),
        Paragraph(f"Tel: {data.company_phone}<br/>Email: {data.company_email}" if (data.company_phone or data.company_email) else "", contact_r),
    ]], colWidths=[96*mm, 82*mm])
    addr_row.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))

    # Rows for the single outer header box. header_inner + addr_row get side
    # padding (they sit inside the box); the tagline band is padding-free so
    # its background colour runs edge-to-edge inside the border.
    header_box_rows = [[header_inner]]
    tagline_row_index = None
    if data.company_tagline:
        tagline_band = Table([[Paragraph(f"<b>{data.company_tagline.upper()}</b>", h_tagline)]], colWidths=[183*mm])
        tagline_band.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1), BRAND_ACCENT),
            ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        tagline_row_index = len(header_box_rows)
        header_box_rows.append([tagline_band])
    header_box_rows.append([addr_row])

    header_card = Table(header_box_rows, colWidths=[183*mm])
    header_card_style = [
        ("BOX",(0,0),(-1,-1),THICK,BORDER),
        ("BACKGROUND",(0,0),(-1,0), BG_SOFT),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]
    if tagline_row_index is not None:
        # Zero out padding just for the tagline row so its accent colour
        # touches the box border on all sides.
        header_card_style += [
            ("LEFTPADDING",(0,tagline_row_index),(-1,tagline_row_index),0),
            ("RIGHTPADDING",(0,tagline_row_index),(-1,tagline_row_index),0),
            ("TOPPADDING",(0,tagline_row_index),(-1,tagline_row_index),0),
            ("BOTTOMPADDING",(0,tagline_row_index),(-1,tagline_row_index),0),
        ]
    header_card.setStyle(TableStyle(header_card_style))

    story.append(header_card)
    story.append(Spacer(1, 2*mm))

    # -- Title strip: PAN | doc label | copy label --
    title_strip = Table([[
        Paragraph(f"<b>PAN: {data.company_pan}</b>" if data.company_pan else "", label8),
        Paragraph(f"<b>{doc_label}</b>", doclabel),
        Paragraph(f"<b>{data.copy_label}</b>", ParagraphStyle("copylbl", fontName=FONT_BOLD, fontSize=8, alignment=TA_RIGHT)),
    ]], colWidths=[55*mm, 73*mm, 55*mm])
    title_strip.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LINEAFTER",(0,0),(1,0),THIN,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))

    # -- Customer Detail | Invoice/Transport Detail --
    cust_lines = [
        [Paragraph("<b>M/S:</b>", label8), Paragraph(data.party_name, body8)],
        [Paragraph("<b>Address:</b>", label8), Paragraph((data.party_address or "").replace("\n","<br/>"), body8)],
        [Paragraph("<b>Phone:</b>", label8), Paragraph(data.party_phone or "-", body8)],
        [Paragraph("<b>GSTIN:</b>", label8), Paragraph(data.party_gstin or "Unregistered", body8)],
        [Paragraph("<b>Place of Supply:</b>", label8), Paragraph(_state_label(data.place_of_supply), body8)],
    ]
    cust_box = Table([[Paragraph("<b>Customer Detail</b>", section_hdr)]] + [[Table(cust_lines, colWidths=[32*mm, 59*mm])]],
                      colWidths=[91*mm])
    cust_box.setStyle(TableStyle([
        ("LINEBELOW",(0,0),(-1,0),0.5,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))

    meta_rows = [["Invoice No:", f"<b>{data.doc_no}</b>", "Invoice Date:", str(data.doc_date)]]
    if data.due_date: meta_rows.append(["Due Date:", str(data.due_date), "", ""])
    meta_rows.append(["Reverse Charge:", "Yes" if getattr(data, "reverse_charge", False) else "No", "", ""])
    if data.challan_no: meta_rows.append(["Challan No:", data.challan_no, "Challan Date:", str(data.challan_date or "")])
    if data.eway_bill_no: meta_rows.append(["E-Way Bill No:", data.eway_bill_no, "", ""])
    if data.transporter_name: meta_rows.append(["Transport:", data.transporter_name, "", ""])
    if data.transporter_id: meta_rows.append(["Transport ID:", data.transporter_id, "", ""])
    if data.vehicle_no: meta_rows.append(["Vehicle No:", data.vehicle_no, "", ""])
    if data.po_no: meta_rows.append(["PO No:", data.po_no, "PO Date:", str(data.po_date or "")])
    meta_table_rows = [[Paragraph(c, label8) if i%2==0 else Paragraph(c, body8) for i,c in enumerate(row)] for row in meta_rows]
    meta_inner = Table(meta_table_rows, colWidths=[32*mm,16*mm,22*mm,22*mm])
    meta_span_style = [
        ("LEFTPADDING",(0,0),(-1,-1),2), ("RIGHTPADDING",(0,0),(-1,-1),2),
        ("TOPPADDING",(0,0),(-1,-1),1.5), ("BOTTOMPADDING",(0,0),(-1,-1),1.5),
    ]
    # Rows that only carry a single label/value pair (Transport, Transport ID,
    # Vehicle No, E-Way Bill No) get their value cell spanned across the
    # remaining columns so long values get the full row width instead of 20mm.
    for row_idx, row in enumerate(meta_rows):
        if row[2] == "" and row[3] == "":
            meta_span_style.append(("SPAN",(1,row_idx),(3,row_idx)))
    meta_inner.setStyle(TableStyle(meta_span_style))
    meta_box = Table([[Paragraph("&nbsp;", section_hdr)]] + [[meta_inner]], colWidths=[92*mm])
    meta_box.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3)]))

    two_col = Table([[cust_box, meta_box]], colWidths=[91*mm, 92*mm])
    two_col.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("LINEAFTER",(0,0),(0,-1),THIN,BORDER),
    ]))

    # -- IRN strip (optional) --
    irn_row = None
    if data.irn:
        irn_text = f"<b>IRN:</b> {data.irn} | <b>Ack No:</b> {data.ack_no or '-'} | <b>Ack Date:</b> {data.ack_date or '-'}"
        irn_row = Table([[Paragraph(irn_text, ParagraphStyle("irn", fontName=FONT_REGULAR, fontSize=6.5))]], colWidths=[183*mm])
        irn_row.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3)]))

    # -- Items table + attached total row (single grid, one font size) --
    is_igst = data.igst_amount > 0
    if is_igst:
        col_headers = ["Sr.\nNo.", "Name of Product/Service", "HSN/\nSAC", "Unit", "Qty", "Rate", "Taxable\nValue", "IGST %", "IGST Amt", "Total"]
        col_widths = [8, 52, 15, 10, 10, 17, 22, 8, 20, 21]
    else:
        col_headers = ["Sr.\nNo.", "Name of Product/Service", "HSN/\nSAC", "Unit", "Qty", "Rate", "Taxable\nValue", "CGST\n%", "CGST\nAmt", "SGST\n%", "SGST\nAmt", "Total"]
        col_widths = [6, 39, 14, 9, 10, 15, 20, 6, 18, 6, 18, 22]
    col_widths = [w * mm for w in col_widths]
    header_style = ParagraphStyle("colh", fontName=FONT_BOLD, fontSize=7, alignment=TA_CENTER, leading=8)

    item_rows = [[Paragraph(h, header_style) for h in col_headers]]
    for item in data.items:
        common = [P(item.get("line_no",""), cell_c), P(item.get("description","") or "-", cell_l),
                  P(item.get("hsn_code","") or "-", cell_c), P(item.get("unit","") or "-", cell_c),
                  P(item.get("quantity",""), cell_r), P(_fmt_compact(item.get("rate",0))), P(_fmt_compact(item.get("taxable_amount",0)))]
        if is_igst:
            tail = [P(f"{item.get('gst_rate',0):g}", cell_c), P(_fmt_compact(item.get("igst_amount",0)))]
        else:
            half = float(item.get("gst_rate",0))/2
            tail = [P(f"{half:g}", cell_c), P(_fmt_compact(item.get("cgst_amount",0))), P(f"{half:g}", cell_c), P(_fmt_compact(item.get("sgst_amount",0)))]
        item_rows.append(common + tail + [P(_fmt_compact(item.get("total_amount",0)))])

    total_qty = sum(float(i.get("quantity",0)) for i in data.items)
    if is_igst:
        item_rows.append(["", Paragraph("Total", tot_bold_l), "", "", Paragraph(f"{total_qty:g}", tot_bold_c), "",
                           Paragraph(_fmt_compact(data.taxable_amount), tot_bold_r), "",
                           Paragraph(_fmt_compact(data.igst_amount), tot_bold_r), Paragraph(_fmt_compact(data.total_amount), tot_bold_r)])
    else:
        item_rows.append(["", Paragraph("Total", tot_bold_l), "", "", Paragraph(f"{total_qty:g}", tot_bold_c), "",
                           Paragraph(_fmt_compact(data.taxable_amount), tot_bold_r), "",
                           Paragraph(_fmt_compact(data.cgst_amount), tot_bold_r), "",
                           Paragraph(_fmt_compact(data.sgst_amount), tot_bold_r), Paragraph(_fmt_compact(data.total_amount), tot_bold_r)])

    items_table = Table(item_rows, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,BORDER),
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),2), ("RIGHTPADDING",(0,0),(-1,-1),2),
        ("BACKGROUND",(0,-1),(-1,-1), LIGHT_GREY),
    ]))

    # -- Total in words | Tax summary --
    # Build tax_box FIRST so we know how tall the right column is, then size
    # words_cell to match — keeping the "Total in words" header pinned to
    # the top, but centering the amount text in the remaining space.
    tax_rows = [["Taxable Amount", _fmt(data.taxable_amount)]]
    if is_igst:
        tax_rows.append(["Add: IGST", _fmt(data.igst_amount)])
    else:
        tax_rows.append(["Add: CGST", _fmt(data.cgst_amount)])
        tax_rows.append(["Add: SGST", _fmt(data.sgst_amount)])
    if data.round_off: tax_rows.append(["Round Off", _fmt(data.round_off)])
    tax_rows.append(["Total Tax", _fmt(float(data.cgst_amount)+float(data.sgst_amount)+float(data.igst_amount))])
    tax_rows.append(["Total Amount After Tax", _fmt(data.total_amount)])
    tax_para = [[Paragraph(r[0], body8), Paragraph(f"<b>{r[1]}</b>" if r[0]=="Total Amount After Tax" else r[1],
                 ParagraphStyle("tval", fontName=FONT_BOLD if r[0]=="Total Amount After Tax" else FONT_REGULAR,
                                fontSize=10 if r[0]=="Total Amount After Tax" else 8, alignment=TA_RIGHT))] for r in tax_rows]
    tax_box = Table(tax_para, colWidths=[38*mm, 35*mm])
    tax_box.setStyle(TableStyle([
        ("LINEABOVE",(0,-1),(-1,-1),0.8,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))

    words_header = Paragraph("<b>Total in words</b>", section_hdr)
    words_amount_style = ParagraphStyle("wordsamt", parent=body8, alignment=TA_CENTER)
    words_amount = Paragraph(amount_in_words(data.total_amount).upper(), words_amount_style)

    tax_box_h = tax_box.wrap(73*mm, 10000*mm)[1]
    header_row_h = words_header.wrap(110*mm, 10000*mm)[1] + 10  # +5/+5 top/bottom padding below
    amount_row_h = max(tax_box_h - header_row_h, words_amount.wrap(102*mm, 10000*mm)[1] + 10)

    words_cell = Table([[words_header], [words_amount]], colWidths=[110*mm],
                        rowHeights=[header_row_h, amount_row_h])
    words_cell.setStyle(TableStyle([
        ("LINEBELOW",(0,0),(-1,0),0.5,BORDER),
        ("VALIGN",(0,0),(-1,0),"TOP"),
        ("VALIGN",(0,1),(-1,1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))

    words_tax_row = Table([[words_cell, tax_box]], colWidths=[110*mm, 73*mm])
    words_tax_row.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("LINEAFTER",(0,0),(0,-1),THIN,BORDER),
    ]))

    # -- Bank Details + QR | Certification + Signature --
    bank_lines = []
    if data.bank_name:
        bank_lines = [
            [Paragraph("Name:", label8), Paragraph(data.bank_name, body8), ""],
            [Paragraph("Branch:", label8), Paragraph(data.bank_branch or "-", body8), ""],
            [Paragraph("Acc. Number:", label8), Paragraph(data.bank_account_no or "-", body8), ""],
            [Paragraph("IFSC:", label8), Paragraph(data.bank_ifsc or "-", body8), ""],
        ]
        if data.upi_id:
            bank_lines.append([Paragraph("UPI ID:", label8), Paragraph(data.upi_id, body8), ""])

    if bank_lines:
        n_rows = len(bank_lines)
        bank_row_style = [
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),2), ("RIGHTPADDING",(0,0),(-1,-1),2),
            ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ]
        if data.upi_id:
            bank_lines[0][2] = [
                _qr_drawing(f"upi://pay?pa={data.upi_id}&pn={data.company_name}&am={float(data.total_amount):.2f}", 26*mm),
                Paragraph("Pay using UPI", ParagraphStyle("payupi", fontName=FONT_BOLD, fontSize=7, alignment=TA_CENTER)),
            ]
            bank_row_style.append(("SPAN",(2,0),(2,n_rows-1)))
            bank_row_style.append(("ALIGN",(2,0),(2,0),"CENTER"))
        bank_row = Table(bank_lines, colWidths=[20*mm, 55*mm, 35*mm])
        bank_row.setStyle(TableStyle(bank_row_style))
    else:
        bank_row = Table([[Paragraph("-", small)]], colWidths=[110*mm])

    tnc_cell = Paragraph(f"<b>Terms and Conditions</b><br/>{(data.terms_conditions or '-').replace(chr(10), '<br/>')}", small)

    bank_box = Table([[Paragraph("<b>Bank Details</b>", section_hdr)], [bank_row], [Spacer(1,2)], [tnc_cell]], colWidths=[110*mm])
    bank_box.setStyle(TableStyle([
        ("LINEBELOW",(0,0),(-1,0),0.5,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))

    sig_box = Table([
        [Paragraph("Certified that the particulars given above are true and correct.", ParagraphStyle("cert", fontName=FONT_REGULAR, fontSize=7, alignment=TA_CENTER))],
        [Paragraph(f"<b>For {data.company_name}</b>", ParagraphStyle("forco", fontName=FONT_BOLD, fontSize=9, alignment=TA_CENTER))],
        [Spacer(1, 6*mm)],
        [Paragraph("This is a computer generated invoice.<br/>No signature required.", ParagraphStyle("stamp", fontName=FONT_REGULAR, fontSize=6.5, alignment=TA_CENTER, textColor=colors.HexColor("#999999")))],
        [Paragraph("Authorised Signatory", ParagraphStyle("sig", fontName=FONT_REGULAR, fontSize=8, alignment=TA_CENTER))],
    ], colWidths=[73*mm])
    sig_box.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5)]))

    bottom_row = Table([[bank_box, sig_box]], colWidths=[110*mm, 73*mm])
    bottom_row.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("LINEAFTER",(0,0),(0,-1),THIN,BORDER),
    ]))

    # -- Pad the items table with blank rows so the footer (totals / bank
    #    details / signature) anchors near the bottom of the page instead of
    #    hugging the last item row, matching standard invoicing software --
    def _flowable_height(f, width):
        try:
            return f.wrap(width, 10000 * mm)[1]
        except Exception:
            return 0

    _table_width = sum(col_widths)

    # Everything already queued in `story` BEFORE the master card (logo/name,
    # tagline band, address row, and the spacers between them) must be
    # counted too, or the budget below runs short and "Thank you" spills
    # onto a second page.
    pre_master_h = sum(_flowable_height(f, 183 * mm) for f in story)

    top_h = _flowable_height(title_strip, 183 * mm) + _flowable_height(two_col, 183 * mm)
    if irn_row is not None:
        top_h += _flowable_height(irn_row, 183 * mm)
    footer_h = _flowable_height(words_tax_row, 183 * mm) + _flowable_height(bottom_row, 183 * mm)

    page_h = A4[1]
    # Leave room below the card for the "Thank you" line + page number,
    # plus a safety margin for sub-pixel wrap-height rounding.
    available_h = page_h - doc.topMargin - doc.bottomMargin - 18 * mm
    target_items_h = available_h - pre_master_h - top_h - footer_h
    current_items_h = _flowable_height(items_table, _table_width)

    if target_items_h > current_items_h:
        blank_style = ParagraphStyle("blankcell", fontName=FONT_REGULAR, fontSize=7, leading=8.5)
        probe = Table([[Paragraph("&nbsp;", blank_style) for _ in col_headers]], colWidths=col_widths)
        probe.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]))
        one_row_h = _flowable_height(probe, _table_width) or 1
        n_filler = int((target_items_h - current_items_h) // one_row_h)
        n_filler = max(0, min(n_filler, 45))  # sanity cap
        if n_filler:
            filler_row = [Paragraph("&nbsp;", blank_style) for _ in col_headers]
            total_row = item_rows[-1]
            item_rows = item_rows[:-1] + [filler_row] * n_filler + [total_row]
            items_table = Table(item_rows, colWidths=col_widths, repeatRows=1)
            items_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("BACKGROUND", (0, -1), (-1, -1), LIGHT_GREY),
            ]))

    # -- Assemble every section into ONE continuous bordered card --
    master_rows = [[title_strip], [two_col]]
    if irn_row is not None:
        master_rows.append([irn_row])
    master_rows.append([items_table])
    master_rows.append([words_tax_row])
    master_rows.append([bottom_row])

    master = Table(master_rows, colWidths=[183*mm])
    master_style = [
        ("BOX",(0,0),(-1,-1),THICK,BORDER),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]
    for i in range(len(master_rows) - 1):
        master_style.append(("LINEBELOW",(0,i),(-1,i),THIN,BORDER))
    master.setStyle(TableStyle(master_style))
    story.append(master)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("Thank you for your business!", ParagraphStyle("thanks", fontName=FONT_REGULAR, fontSize=9)))

    def _page_footer(canvas, doc_):
        canvas.saveState()
        page_w, _ = A4
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.setFont(FONT_REGULAR, 6.5)
        canvas.drawRightString(page_w - 8*mm, 5*mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()

def generate_purchase_order_pdf(data: PDFDocumentData) -> bytes:
    """Dedicated Purchase Order layout — a procurement document, not a payment
    document. Shares the same visual identity (fonts, header, GST logic) as
    generate_invoice_pdf, restructured with PO-specific sections."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=8*mm, leftMargin=8*mm,
                             topMargin=8*mm, bottomMargin=8*mm)
    BORDER = colors.black
    THIN = 0.6
    THICK = 1.2

    h_company = ParagraphStyle("hco", fontName=FONT_BOLD, fontSize=21, textColor=BRAND_DARK, leading=24)
    h_tagline = ParagraphStyle("htag", fontName=FONT_BOLD, fontSize=9.5, textColor=colors.white, alignment=TA_CENTER)
    contact = ParagraphStyle("contact", fontName=FONT_REGULAR, fontSize=8, textColor=TEXT_DARK, leading=11)
    contact_r = ParagraphStyle("contactr", parent=contact, alignment=TA_RIGHT)
    doclabel = ParagraphStyle("doclabel", fontName=FONT_BOLD, fontSize=18, alignment=TA_CENTER, leading=22)
    label8 = ParagraphStyle("label8", fontName=FONT_BOLD, fontSize=8)
    body8 = ParagraphStyle("body8", fontName=FONT_REGULAR, fontSize=8, leading=11)
    body8_c = ParagraphStyle("body8c", parent=body8, alignment=TA_CENTER)
    section_hdr = ParagraphStyle("sechdr", fontName=FONT_BOLD, fontSize=8, alignment=TA_CENTER)
    small = ParagraphStyle("small", fontName=FONT_REGULAR, fontSize=7)

    cell_l = ParagraphStyle("celll", fontName=FONT_REGULAR, fontSize=7, alignment=TA_LEFT, leading=8.5)
    cell_c = ParagraphStyle("cellc", fontName=FONT_REGULAR, fontSize=7, alignment=TA_CENTER, leading=8.5)
    cell_r = ParagraphStyle("cellr", fontName=FONT_REGULAR, fontSize=7, alignment=TA_RIGHT, leading=8.5)
    tot_bold_l = ParagraphStyle("totboldl", fontName=FONT_BOLD, fontSize=7, alignment=TA_LEFT)
    tot_bold_c = ParagraphStyle("totboldc", fontName=FONT_BOLD, fontSize=7, alignment=TA_CENTER)
    tot_bold_r = ParagraphStyle("totboldr", fontName=FONT_BOLD, fontSize=7, alignment=TA_RIGHT)

    def P(v, style=cell_r):
        return Paragraph(str(v) if v not in (None, "") else "-", style)

    story = []

    # -- Company header band (identical to Tax Invoice) --
    logo_flowable = ""
    if data.company_logo_url:
        logo_path = ("app" + data.company_logo_url) if data.company_logo_url.startswith("/static/") else data.company_logo_url
        if os.path.exists(logo_path):
            try:
                from PIL import Image as PILImage
                with PILImage.open(logo_path) as im:
                    iw, ih = im.size
                max_dim = 20 * mm
                scale = max_dim / max(iw, ih)
                logo_flowable = RLImage(logo_path, width=iw * scale, height=ih * scale)
            except Exception:
                logo_flowable = ""

    header_inner = Table([[logo_flowable, Paragraph(f"<b>{data.company_name or 'Company Name'}</b>", h_company)]],
                          colWidths=[24*mm, 154*mm])
    header_inner.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("ALIGN",(0,0),(0,0),"CENTER"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))

    addr_row = Table([[
        Paragraph((data.company_address or "").replace("\n", "<br/>"), contact),
        Paragraph(f"Tel: {data.company_phone}<br/>Email: {data.company_email}" if (data.company_phone or data.company_email) else "", contact_r),
    ]], colWidths=[96*mm, 82*mm])
    addr_row.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))

    header_box_rows = [[header_inner]]
    tagline_row_index = None
    if data.company_tagline:
        tagline_band = Table([[Paragraph(f"<b>{data.company_tagline.upper()}</b>", h_tagline)]], colWidths=[183*mm])
        tagline_band.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1), BRAND_ACCENT),
            ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        tagline_row_index = len(header_box_rows)
        header_box_rows.append([tagline_band])
    header_box_rows.append([addr_row])

    header_card = Table(header_box_rows, colWidths=[183*mm])
    header_card_style = [
        ("BOX",(0,0),(-1,-1),THICK,BORDER),
        ("BACKGROUND",(0,0),(-1,0), BG_SOFT),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]
    if tagline_row_index is not None:
        header_card_style += [
            ("LEFTPADDING",(0,tagline_row_index),(-1,tagline_row_index),0),
            ("RIGHTPADDING",(0,tagline_row_index),(-1,tagline_row_index),0),
            ("TOPPADDING",(0,tagline_row_index),(-1,tagline_row_index),0),
            ("BOTTOMPADDING",(0,tagline_row_index),(-1,tagline_row_index),0),
        ]
    header_card.setStyle(TableStyle(header_card_style))
    story.append(header_card)
    story.append(Spacer(1, 2*mm))

    # -- Title strip --
    title_strip = Table([[
        Paragraph(f"<b>PAN: {data.company_pan}</b>" if data.company_pan else "", label8),
        Paragraph("<b>PURCHASE ORDER</b>", doclabel),
        Paragraph("<b>FOR SUPPLIER</b>", ParagraphStyle("copylbl", fontName=FONT_BOLD, fontSize=8, alignment=TA_RIGHT)),
    ]], colWidths=[55*mm, 73*mm, 55*mm])
    title_strip.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LINEAFTER",(0,0),(1,0),THIN,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))

    # -- Document Information: PO No, PO Date, Expected Delivery, Supplier Ref,
    #    Buyer, Payment Terms, Delivery Terms, Status. Empty optional fields
    #    are skipped entirely rather than shown as "-". --
    status_colors = {
        "draft": colors.HexColor("#6B7280"), "approved": GOOD_GREEN, "sent": BRAND_BLUE,
        "acknowledged": BRAND_BLUE, "partial": WARN_ORANGE, "received": GOOD_GREEN,
        "closed": colors.HexColor("#6B7280"), "cancelled": BAD_RED,
    }
    status_val = (data.status or "draft").lower()
    status_style = ParagraphStyle("statusval", fontName=FONT_BOLD, fontSize=8,
                                   textColor=status_colors.get(status_val, colors.HexColor("#6B7280")))

    info_pairs = [("PO No.", f"<b>{data.doc_no}</b>", body8), ("PO Date", str(data.doc_date), body8)]
    if data.expected_delivery: info_pairs.append(("Expected Delivery", str(data.expected_delivery), body8))
    if data.supplier_ref: info_pairs.append(("Supplier Reference", data.supplier_ref, body8))
    if data.buyer_contact: info_pairs.append(("Buyer", data.buyer_contact, body8))
    if data.payment_terms: info_pairs.append(("Payment Terms", data.payment_terms, body8))
    if data.delivery_terms: info_pairs.append(("Delivery Terms", data.delivery_terms, body8))
    info_pairs.append(("Status", (data.status or "Draft").title(), status_style))

    info_grid_rows = []
    for i in range(0, len(info_pairs), 2):
        left = info_pairs[i]
        right = info_pairs[i+1] if i+1 < len(info_pairs) else None
        row = [
            Paragraph(f"{left[0]}:", label8), Paragraph(left[1], left[2]),
            Paragraph(f"{right[0]}:", label8) if right else "",
            Paragraph(right[1], right[2]) if right else "",
        ]
        info_grid_rows.append(row)
    info_grid = Table(info_grid_rows, colWidths=[28*mm, 63*mm, 28*mm, 64*mm])
    info_grid.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),2), ("RIGHTPADDING",(0,0),(-1,-1),2),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))
    info_box = Table([[Paragraph("<b>Purchase Order Information</b>", section_hdr)], [info_grid]], colWidths=[183*mm])
    info_box.setStyle(TableStyle([
        ("LINEBELOW",(0,0),(-1,0),0.5,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))

    # -- Supplier Details | Delivery Address (two aligned sections) --
    supplier_lines = [[Paragraph("<b>M/S:</b>", label8), Paragraph(data.party_name or "-", body8)]]
    if data.party_address:
        supplier_lines.append([Paragraph("<b>Address:</b>", label8), Paragraph(data.party_address.replace("\n","<br/>"), body8)])
    if data.party_phone:
        supplier_lines.append([Paragraph("<b>Phone:</b>", label8), Paragraph(data.party_phone, body8)])
    supplier_lines.append([Paragraph("<b>GSTIN:</b>", label8), Paragraph(data.party_gstin or "Unregistered", body8)])
    if data.place_of_supply:
        supplier_lines.append([Paragraph("<b>Place of Supply:</b>", label8), Paragraph(_state_label(data.place_of_supply), body8)])
    supplier_box = Table([[Paragraph("<b>Supplier Details</b>", section_hdr)]] + [[Table(supplier_lines, colWidths=[30*mm, 61*mm])]],
                          colWidths=[91*mm])
    supplier_box.setStyle(TableStyle([
        ("LINEBELOW",(0,0),(-1,0),0.5,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))

    deliver_box = Table([
        [Paragraph("<b>Delivery Address</b>", section_hdr)],
        [Paragraph((data.delivery_address or data.company_address or "Same as company address").replace("\n","<br/>"), body8)],
    ], colWidths=[92*mm])
    deliver_box.setStyle(TableStyle([
        ("LINEBELOW",(0,0),(-1,0),0.5,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))

    two_col = Table([[supplier_box, deliver_box]], colWidths=[91*mm, 92*mm])
    two_col.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("LINEAFTER",(0,0),(0,-1),THIN,BORDER),
    ]))

    # -- Items table: Sr, Item Description, HSN/SAC, Unit, Qty, Rate, GST%, Amount --
    col_headers = ["Sr.\nNo.", "Item Description", "HSN/\nSAC", "Unit", "Qty", "Rate", "GST\n%", "Amount"]
    col_widths = [w * mm for w in [8, 55, 16, 14, 14, 22, 14, 40]]
    header_style = ParagraphStyle("colh", fontName=FONT_BOLD, fontSize=7, alignment=TA_CENTER, leading=8)

    item_rows = [[Paragraph(h, header_style) for h in col_headers]]
    for item in data.items:
        item_rows.append([
            P(item.get("line_no",""), cell_c),
            P(item.get("description","") or "-", cell_l),
            P(item.get("hsn_code","") or "-", cell_c),
            P(item.get("unit","") or "-", cell_c),
            P(item.get("quantity",""), cell_r),
            P(_fmt(item.get("rate",0))),
            P(f"{float(item.get('gst_rate',0)):g}", cell_c),
            P(_fmt(item.get("total_amount",0))),
        ])

    total_qty = sum(float(i.get("quantity",0)) for i in data.items)
    item_rows.append([
        "", Paragraph("Total", tot_bold_l), "", "",
        Paragraph(f"{total_qty:g}", tot_bold_c), "", "",
        Paragraph(_fmt(data.total_amount), tot_bold_r),
    ])

    items_table = Table(item_rows, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,BORDER),
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),2), ("RIGHTPADDING",(0,0),(-1,-1),2),
        ("BACKGROUND",(0,-1),(-1,-1), LIGHT_GREY),
    ]))

    # -- Total in words (center-aligned) | Bordered totals summary --
    words_cell = Table([
        [Paragraph("<b>Total in Words</b>", section_hdr)],
        [Paragraph(amount_in_words(data.total_amount).upper(), body8_c)],
    ], colWidths=[110*mm])
    words_cell.setStyle(TableStyle([
        ("LINEBELOW",(0,0),(-1,0),0.5,BORDER),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))

    is_igst = data.igst_amount > 0
    tax_rows = [["Taxable Amount", _fmt(data.taxable_amount)]]
    if is_igst:
        tax_rows.append(["Add: IGST", _fmt(data.igst_amount)])
    else:
        tax_rows.append(["Add: CGST", _fmt(data.cgst_amount)])
        tax_rows.append(["Add: SGST", _fmt(data.sgst_amount)])
    if data.round_off: tax_rows.append(["Round Off", _fmt(data.round_off)])
    tax_rows.append(["Total Tax", _fmt(float(data.cgst_amount)+float(data.sgst_amount)+float(data.igst_amount))])
    tax_rows.append(["Total Amount After Tax", _fmt(data.total_amount)])
    tax_para = [[Paragraph(r[0], body8), Paragraph(f"<b>{r[1]}</b>" if r[0]=="Total Amount After Tax" else r[1],
                 ParagraphStyle("tval", fontName=FONT_BOLD if r[0]=="Total Amount After Tax" else FONT_REGULAR,
                                fontSize=10 if r[0]=="Total Amount After Tax" else 8, alignment=TA_RIGHT))] for r in tax_rows]
    tax_box = Table(tax_para, colWidths=[38*mm, 35*mm])
    tax_box.setStyle(TableStyle([
        ("LINEABOVE",(0,-1),(-1,-1),0.8,BORDER),
        ("BACKGROUND",(0,-1),(-1,-1), BG_SOFT),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))

    words_tax_row = Table([[words_cell, tax_box]], colWidths=[110*mm, 73*mm])
    words_tax_row.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("LINEAFTER",(0,0),(0,-1),THIN,BORDER),
    ]))

    # -- Remarks & Terms | Signature (Prepared By / Approved By / Authorised Signatory) --
    po_standard_terms = [
        "Please supply the items strictly as per the specifications mentioned above.",
        "Goods are subject to inspection and quality check upon receipt.",
        "Delivery must be completed on or before the expected delivery date.",
        "Tax Invoice must accompany the shipment.",
        "Supplier must acknowledge receipt of this Purchase Order.",
        "Any change in quantity, price, or specifications requires prior written approval.",
    ]
    if data.terms_conditions:
        # A PO-level or Settings-level override replaces the built-in defaults
        # entirely, rather than stacking below them.
        terms_html = data.terms_conditions.replace("\n", "<br/>")
    else:
        terms_html = "<br/>".join(f"&#8226; {t}" for t in po_standard_terms)
    remarks_para = [Paragraph(f"<b>Remarks:</b> {data.remarks}", small)] if data.remarks else []
    terms_cell = Paragraph(f"<b>Terms &amp; Conditions</b><br/>{terms_html}", small)

    remarks_box = Table([[Paragraph("<b>Remarks &amp; Terms</b>", section_hdr)]] + [[r] for r in remarks_para] +
                         [[Spacer(1,3)], [terms_cell]], colWidths=[110*mm])
    remarks_box.setStyle(TableStyle([
        ("LINEBELOW",(0,0),(-1,0),0.5,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))

    sig_lbl = ParagraphStyle("siglbl", fontName=FONT_REGULAR, fontSize=6, alignment=TA_CENTER)
    sig_line_row = Table([
        ["", "", ""],
        [Paragraph("Prepared By", sig_lbl), Paragraph("Approved By", sig_lbl), Paragraph("Authorised Signatory", sig_lbl)],
    ], colWidths=[24*mm, 24*mm, 25*mm], rowHeights=[9*mm, None])
    sig_line_row.setStyle(TableStyle([
        ("LINEABOVE",(0,1),(-1,1),0.6,BORDER),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("TOPPADDING",(0,1),(-1,1),2), ("BOTTOMPADDING",(0,0),(-1,-1),0),
        ("LEFTPADDING",(0,0),(-1,-1),1), ("RIGHTPADDING",(0,0),(-1,-1),1),
    ]))

    sig_box = Table([
        [Paragraph("Certified that the above Purchase Order is issued on behalf of the company.", ParagraphStyle("cert", fontName=FONT_REGULAR, fontSize=6.5, alignment=TA_CENTER))],
        [Paragraph(f"<b>For {data.company_name}</b>", ParagraphStyle("forco", fontName=FONT_BOLD, fontSize=9, alignment=TA_CENTER))],
        [Spacer(1, 4*mm)],
        [sig_line_row],
        [Paragraph("This is a system-generated Purchase Order.", ParagraphStyle("stamp", fontName=FONT_REGULAR, fontSize=6, alignment=TA_CENTER, textColor=colors.HexColor("#999999")))],
    ], colWidths=[73*mm])
    sig_box.setStyle(TableStyle([
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
    ]))

    bottom_row = Table([[remarks_box, sig_box]], colWidths=[110*mm, 73*mm])
    bottom_row.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("LINEAFTER",(0,0),(0,-1),THIN,BORDER),
    ]))

    # -- Assemble --
    master_rows = [[title_strip], [info_box], [two_col], [items_table], [words_tax_row], [bottom_row]]
    master = Table(master_rows, colWidths=[183*mm])
    master_style = [
        ("BOX",(0,0),(-1,-1),THICK,BORDER),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]
    for i in range(len(master_rows) - 1):
        master_style.append(("LINEBELOW",(0,i),(-1,i),THIN,BORDER))
    master.setStyle(TableStyle(master_style))
    story.append(master)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("Kindly acknowledge receipt and confirm the delivery schedule.",
                            ParagraphStyle("thanks", fontName=FONT_REGULAR, fontSize=9)))

    def _page_footer(canvas, doc_):
        canvas.saveState()
        page_w, _ = A4
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.setFont(FONT_REGULAR, 6.5)
        canvas.drawRightString(page_w - 8*mm, 5*mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()

# ── Font setup: register Noto Sans for proper ₹ glyph + clean typography ──────
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend
from reportlab.lib.pagesizes import A4 as A4_SIZE


BRAND_ACCENT = colors.HexColor("#00C2A8")
BG_SOFT      = colors.HexColor("#F0F4FA")
GREEN        = colors.HexColor("#0E9F6E")
ORANGE       = colors.HexColor("#E8720C")
RED          = colors.HexColor("#DC2626")


def format_inr(amount) -> str:
    """Indian numbering with non-breaking currency symbol: ₹17,84,963.00"""
    amount = float(amount or 0)
    neg = amount < 0
    amount = abs(amount)
    whole, _, frac = f"{amount:,.2f}".partition(".")
    whole = whole.replace(",", "")
    if len(whole) > 3:
        last3, rest = whole[-3:], whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        whole = ",".join(groups) + "," + last3
    symbol = "\u20b9" if FONT_REGULAR == "NotoSans" else "Rs."
    sep = "" if symbol == "\u20b9" else "\u00a0"  # non-breaking space keeps "Rs." glued to the number
    return f"{'-' if neg else ''}{symbol}{sep}{whole}.{frac}"


def _header_footer(canvas, doc, title: str, company: dict, period: str, generated_by: str):
    canvas.saveState()
    page_w, page_h = A4_SIZE

    canvas.setFillColor(BRAND_DARK)
    canvas.rect(0, page_h - 34*mm, page_w, 34*mm, fill=1, stroke=0)

    # Left block — company identity
    x = 16*mm
    canvas.setFillColor(colors.white)
    canvas.setFont(FONT_BOLD, 15)
    canvas.drawString(x, page_h - 12*mm, company.get("legal_name") or "Company")
    canvas.setFont(FONT_REGULAR, 8)
    canvas.setFillColor(colors.HexColor("#B8C4D9"))
    line_y = page_h - 17*mm
    details = []
    if company.get("reg_address"):
        addr_lines = [ln.strip().rstrip(",").strip() for ln in company["reg_address"].replace("\r", "").split("\n")]
        addr_lines = [ln for ln in addr_lines if ln]
        details.append(", ".join(addr_lines)[:60])
    if company.get("gstin"): details.append(f"GSTIN: {company['gstin']}")
    contact_bits = [b for b in [company.get("phone"), company.get("email"), company.get("website")] if b]
    if contact_bits: details.append(" · ".join(contact_bits))
    for line in details[:3]:
        canvas.drawString(x, line_y, line)
        line_y -= 4*mm

    # Right block — report metadata
    rx = page_w - 16*mm
    canvas.setFont(FONT_BOLD, 12)
    canvas.setFillColor(BRAND_ACCENT)
    canvas.drawRightString(rx, page_h - 12*mm, title)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.setFillColor(colors.HexColor("#B8C4D9"))
    meta_lines = [
        f"Generated: {datetime.now().strftime('%d %b %Y, %I:%M %p')}",
        f"Period: {period}",
        f"Generated By: {generated_by}",
    ]
    my = page_h - 17*mm
    for line in meta_lines:
        canvas.drawRightString(rx, my, line)
        my -= 4*mm

    # Footer
    canvas.setFillColor(colors.HexColor("#999999"))
    canvas.setFont(FONT_REGULAR, 7.5)
    canvas.drawString(16*mm, 10*mm, "Generated by VyaparPro ERP")
    canvas.drawCentredString(page_w/2, 10*mm, "Confidential – Internal Use Only")
    canvas.drawRightString(page_w - 16*mm, 10*mm, f"Page {doc.page}")
    canvas.setStrokeColor(MED_GREY)
    canvas.line(16*mm, 14*mm, page_w - 16*mm, 14*mm)
    canvas.restoreState()


def _kpi_cards(summary: list[tuple[str, str, str]]) -> Table:
    """summary: list of (label, value, accent) where accent in {'blue','green','orange','red'}"""
    accent_map = {"blue": BRAND_BLUE, "green": GREEN, "orange": ORANGE, "red": RED}
    cells, styles = [], []
    for i, (label, value, accent) in enumerate(summary):
        color = accent_map.get(accent, BRAND_BLUE)
        cell = Table([[Paragraph(f'<font color="#666666" size="8">{label.upper()}</font>')],
                      [Paragraph(f'<font color="{color.hexval()}" size="12"><b>{value}</b></font>')]],
                     colWidths=[48*mm])
        cell.setStyle(TableStyle([
            ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("LEFTPADDING", (0,0), (-1,-1), 10), ("BACKGROUND", (0,0), (-1,-1), BG_SOFT),
            ("LINEBELOW", (0,0), (-1,0), 2.5, color), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        cells.append(cell)
    row = Table([cells], colWidths=[50*mm]*len(cells))
    row.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),3),
                              ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0)]))
    return row


def _bar_chart(categories: list[str], values: list[float], title: str) -> Drawing:
    n = len(categories)
    max_val = max(values) if values else 1
    longest_label = max((len(c) for c in categories), default=10)
    left_margin = min(max(35*mm, longest_label * 1.6*mm), 65*mm)
    bar_h = 6*mm
    chart_height = n * bar_h + 10*mm
    chart_width = 170*mm - left_margin - 20*mm  # reserve room for value labels past bar end

    d = Drawing(170*mm, chart_height + 8*mm)
    chart = HorizontalBarChart()
    chart.x, chart.y = left_margin, 5*mm
    chart.width, chart.height = chart_width, n * bar_h
    chart.data = [values]
    chart.categoryAxis.categoryNames = categories
    chart.categoryAxis.labels.fontName = FONT_REGULAR
    chart.categoryAxis.labels.fontSize = 7.5
    chart.categoryAxis.labels.maxWidth = left_margin - 4*mm
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max_val * 1.25 if max_val else 1
    chart.valueAxis.labels.fontName = FONT_REGULAR
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = BRAND_BLUE
    chart.barWidth = bar_h * 0.65
    chart.barSpacing = bar_h * 0.35
    d.add(chart)

    # Draw value labels manually, past the end of each bar — never inside, never clipped
    for i, val in enumerate(values):
        bar_len = (val / chart.valueAxis.valueMax) * chart_width if chart.valueAxis.valueMax else 0
        y = chart.y + i * bar_h + bar_h * 0.32
        label = format_inr(val) if val >= 1000 else f"{val:.0f}"
        d.add(String(chart.x + bar_len + 3*mm, y, label, fontName=FONT_REGULAR, fontSize=7, fillColor=BRAND_DARK))
    return d


def _pie_chart(labels: list[str], values: list[float]) -> Drawing:
    palette = [BRAND_BLUE, GREEN, ORANGE, BRAND_ACCENT, RED, colors.HexColor("#8B5CF6"), colors.HexColor("#EC4899")]
    d = Drawing(170*mm, 55*mm)
    pie = Pie()
    pie.x, pie.y = 20*mm, 5*mm
    pie.width, pie.height = 45*mm, 45*mm
    pie.data = values
    pie.labels = None
    for i in range(len(values)):
        pie.slices[i].fillColor = palette[i % len(palette)]
        pie.slices[i].strokeColor = colors.white
        pie.slices[i].strokeWidth = 1
    d.add(pie)
    legend = Legend()
    legend.x, legend.y = 75*mm, 40*mm
    legend.dx, legend.dy = 3*mm, 3*mm
    legend.fontName = FONT_REGULAR
    legend.fontSize = 8
    legend.colorNamePairs = [(palette[i % len(palette)], f"{labels[i][:20]} ({values[i]:.0f})") for i in range(len(values))]
    d.add(legend)
    return d


def generate_report_pdf(title: str, subtitle: str, summary: list, tables: list,
                         company: dict | None = None, period: str = "",
                         generated_by: str = "System", bar_chart: dict | None = None,
                         pie_chart: dict | None = None) -> bytes:
    """
    summary: list of (label, value) OR (label, value, accent) tuples
    tables:  list of (section_title, headers, rows)
    bar_chart: {"title": str, "categories": [...], "values": [...]} or None
    pie_chart: {"labels": [...], "values": [...]} or None
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=40*mm, bottomMargin=20*mm,
                             leftMargin=16*mm, rightMargin=16*mm)
    styles = getSampleStyleSheet()
    section_style = ParagraphStyle("RSection", fontName=FONT_BOLD, fontSize=12,
                                    textColor=BRAND_DARK, spaceBefore=16, spaceAfter=8)

    story = [Spacer(1, 4*mm)]

    if summary:
        summary_norm = [(s if len(s) == 3 else (*s, "blue")) for s in summary]
        story.append(_kpi_cards(summary_norm))
        story.append(Spacer(1, 6*mm))

    if bar_chart and bar_chart.get("values"):
        story.append(Paragraph(bar_chart.get("title", "Overview"), section_style))
        story.append(_bar_chart(bar_chart["categories"], bar_chart["values"], bar_chart.get("title", "")))
        story.append(Spacer(1, 4*mm))

    if pie_chart and pie_chart.get("values"):
        story.append(Paragraph(pie_chart.get("title", "Distribution"), section_style))
        story.append(_pie_chart(pie_chart["labels"], pie_chart["values"]))
        story.append(Spacer(1, 4*mm))

    _NUMERIC_HEADERS = {
        "debit", "credit", "balance", "amount", "opening dr", "opening cr",
        "period dr", "period cr", "closing dr", "closing cr", "receipt", "payment",
    }
    _cell_style = ParagraphStyle("RCell", fontName=FONT_REGULAR, fontSize=8, leading=10, wordWrap="CJK")
    _cell_style_r = ParagraphStyle("RCellR", parent=_cell_style, alignment=TA_RIGHT)
    _head_style = ParagraphStyle("RHead", fontName=FONT_BOLD, fontSize=8.5, leading=10,
                                  textColor=colors.white, wordWrap="CJK")
    _head_style_r = ParagraphStyle("RHeadR", parent=_head_style, alignment=TA_RIGHT)

    for section_title, headers, rows in tables:
        story.append(Paragraph(section_title, section_style))
        if not rows:
            story.append(Paragraph("No data for this period", styles["Normal"]))
            continue

        n_cols = len(headers)
        is_numeric_col = [h.strip().lower() in _NUMERIC_HEADERS for h in headers]

        # Weight columns by their actual content length (so Narration gets room and
        # Date/Voucher don't), then rescale to exactly fill the page width.
        all_rows = [headers] + rows
        raw_weights = [
            max((len(str(r[c])) for r in all_rows if len(r) > c), default=4)
            for c in range(n_cols)
        ]
        min_w, max_w = 16 * mm, 70 * mm
        col_widths = [w / sum(raw_weights) * doc.width for w in raw_weights]
        col_widths = [min(max(w, min_w), max_w) for w in col_widths]
        scale = doc.width / sum(col_widths)
        col_widths = [w * scale for w in col_widths]

        header_row = [
            Paragraph(str(h), _head_style_r if is_numeric_col[i] else _head_style)
            for i, h in enumerate(headers)
        ]
        data = [header_row]
        for r in rows:
            data.append([
                Paragraph(str(val) if val not in (None, "") else "—",
                          _cell_style_r if (i < len(is_numeric_col) and is_numeric_col[i]) else _cell_style)
                for i, val in enumerate(r)
            ])

        t = Table(data, colWidths=col_widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0,0), (-1,0), BRAND_DARK),
            ("GRID", (0,0), (-1,-1), 0.4, MED_GREY),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, BG_SOFT]),
            ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]
        t.setStyle(TableStyle(style))
        story.append(t)
        story.append(Spacer(1, 4*mm))

    def _on_page(canvas, doc_):
        _header_footer(canvas, doc_, title, company or {}, period, generated_by)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()