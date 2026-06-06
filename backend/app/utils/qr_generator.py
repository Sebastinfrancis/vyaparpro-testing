"""
VyaparPro — Barcode & QR Code Generator
Generates CODE128, EAN13, QR codes as PNG bytes or base64 strings.
"""
from __future__ import annotations

import base64
import io
import json
from typing import Any

try:
    import qrcode
    from qrcode.image.pil import PilImage
    _QR_OK = True
except ImportError:
    _QR_OK = False

try:
    from barcode import Code128, EAN13
    from barcode.writer import ImageWriter
    _BC_OK = True
except ImportError:
    _BC_OK = False


def generate_qr_bytes(data: str | dict, box_size: int = 6, border: int = 2) -> bytes:
    """Generate a QR code PNG from string or dict. Returns raw PNG bytes."""
    if not _QR_OK:
        raise RuntimeError("qrcode library not installed. Run: pip install qrcode[pil]")
    payload = json.dumps(data, default=str) if isinstance(data, dict) else data
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def generate_qr_base64(data: str | dict) -> str:
    """Return QR code as base64-encoded PNG string (embeddable in HTML/Flutter)."""
    raw = generate_qr_bytes(data)
    return base64.b64encode(raw).decode()


def generate_code128_bytes(value: str) -> bytes:
    """Generate a CODE128 barcode PNG. Returns raw bytes."""
    if not _BC_OK:
        raise RuntimeError("python-barcode not installed. Run: pip install python-barcode[images]")
    buf = io.BytesIO()
    barcode = Code128(value, writer=ImageWriter())
    barcode.write(buf, options={"write_text": True, "module_height": 10.0, "quiet_zone": 2.0})
    buf.seek(0)
    return buf.read()


def generate_code128_base64(value: str) -> str:
    return base64.b64encode(generate_code128_bytes(value)).decode()


def build_product_qr_data(
    product_id: str,
    product_code: str,
    product_name: str,
    batch_no: str = "",
    serial_no: str = "",
    company_id: str = "",
) -> dict[str, Any]:
    """Standard QR payload for a product label."""
    return {
        "t": "product",
        "cid": company_id,
        "pid": product_id,
        "code": product_code,
        "name": product_name,
        "batch": batch_no,
        "serial": serial_no,
    }


def build_invoice_qr_data(
    invoice_no: str,
    invoice_date: str,
    gstin_seller: str,
    gstin_buyer: str,
    taxable_amount: str,
    total_gst: str,
    total_amount: str,
    irn: str = "",
) -> dict[str, Any]:
    """Standard QR payload for e-invoice (NIC format subset)."""
    return {
        "t": "invoice",
        "inv": invoice_no,
        "dt": invoice_date,
        "seller": gstin_seller,
        "buyer": gstin_buyer,
        "taxable": taxable_amount,
        "gst": total_gst,
        "total": total_amount,
        "irn": irn,
    }
