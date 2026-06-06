"""
VyaparPro — GST Calculation Engine
Handles CGST+SGST (intra-state) and IGST (inter-state) splits,
reverse charge, composite scheme, CESS, and line-item rounding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional


def _r(v: Decimal, places: int = 2) -> Decimal:
    """Round to n decimal places using ROUND_HALF_UP."""
    q = Decimal(10) ** -places
    return v.quantize(q, rounding=ROUND_HALF_UP)


@dataclass
class LineItemGST:
    """Per-line GST computation result."""
    line_no: int
    description: str
    hsn_code: str = ""
    quantity: Decimal = Decimal("1")
    rate: Decimal = Decimal("0")
    discount_pct: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    taxable_amount: Decimal = Decimal("0")
    gst_rate: Decimal = Decimal("0")
    cgst_rate: Decimal = Decimal("0")
    sgst_rate: Decimal = Decimal("0")
    igst_rate: Decimal = Decimal("0")
    cess_rate: Decimal = Decimal("0")
    cgst_amount: Decimal = Decimal("0")
    sgst_amount: Decimal = Decimal("0")
    igst_amount: Decimal = Decimal("0")
    cess_amount: Decimal = Decimal("0")
    total_gst: Decimal = Decimal("0")
    total_amount: Decimal = Decimal("0")


@dataclass
class GSTSummary:
    """Document-level GST totals."""
    subtotal: Decimal = Decimal("0")
    total_discount: Decimal = Decimal("0")
    total_taxable: Decimal = Decimal("0")
    total_cgst: Decimal = Decimal("0")
    total_sgst: Decimal = Decimal("0")
    total_igst: Decimal = Decimal("0")
    total_cess: Decimal = Decimal("0")
    total_gst: Decimal = Decimal("0")
    other_charges: Decimal = Decimal("0")
    round_off: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")
    lines: list[LineItemGST] = field(default_factory=list)

    # HSN-wise summary (for GSTR-1)
    hsn_summary: list[dict] = field(default_factory=list)


class GSTCalculator:
    """
    Compute GST for any billing document.

    Usage:
        calc = GSTCalculator(supply_type="intra", reverse_charge=False)
        summary = calc.compute(items=[...], other_charges=Decimal("200"))
    """

    VALID_SUPPLY_TYPES = {
        "intra",           # CGST + SGST
        "inter",           # IGST only
        "export_with_gst", # IGST (with refund)
        "export_without_gst",  # 0% GST
        "sez_with_gst",
        "sez_without_gst",
        "nil",             # fully exempt
    }

    def __init__(
        self,
        supply_type: str = "intra",
        reverse_charge: bool = False,
        composition_scheme: bool = False,
    ) -> None:
        if supply_type not in self.VALID_SUPPLY_TYPES:
            raise ValueError(f"Unknown supply_type: {supply_type}")
        self.supply_type = supply_type
        self.reverse_charge = reverse_charge
        self.composition_scheme = composition_scheme
        self._is_igst = supply_type in ("inter", "export_with_gst", "sez_with_gst")
        self._zero_gst = supply_type in ("export_without_gst", "sez_without_gst", "nil")

    def _split_rates(self, gst_rate: Decimal, cess_rate: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """Returns (cgst_rate, sgst_rate, igst_rate, cess_rate) based on supply type."""
        if self._zero_gst or self.reverse_charge:
            return Decimal("0"), Decimal("0"), Decimal("0"), cess_rate
        if self._is_igst:
            return Decimal("0"), Decimal("0"), gst_rate, cess_rate
        # Intra-state: split equally
        half = _r(gst_rate / 2, 3)
        return half, half, Decimal("0"), cess_rate

    def compute_line(
        self,
        line_no: int,
        description: str,
        quantity: Decimal,
        rate: Decimal,
        gst_rate: Decimal,
        cess_rate: Decimal = Decimal("0"),
        discount_pct: Decimal = Decimal("0"),
        discount_amount: Decimal = Decimal("0"),
        hsn_code: str = "",
    ) -> LineItemGST:
        gross = _r(quantity * rate)
        # Discount: explicit amount takes priority over %
        if discount_amount > 0:
            disc = _r(discount_amount)
        elif discount_pct > 0:
            disc = _r(gross * discount_pct / 100)
        else:
            disc = Decimal("0")

        taxable = _r(gross - disc)
        cgst_r, sgst_r, igst_r, cess_r = self._split_rates(gst_rate, cess_rate)

        cgst = _r(taxable * cgst_r / 100)
        sgst = _r(taxable * sgst_r / 100)
        igst = _r(taxable * igst_r / 100)
        cess = _r(taxable * cess_r / 100)
        total_gst = cgst + sgst + igst + cess
        total = taxable + total_gst

        return LineItemGST(
            line_no=line_no,
            description=description,
            hsn_code=hsn_code,
            quantity=quantity,
            rate=rate,
            discount_pct=discount_pct,
            discount_amount=disc,
            taxable_amount=taxable,
            gst_rate=gst_rate,
            cgst_rate=cgst_r,
            sgst_rate=sgst_r,
            igst_rate=igst_r,
            cess_rate=cess_r,
            cgst_amount=cgst,
            sgst_amount=sgst,
            igst_amount=igst,
            cess_amount=cess,
            total_gst=total_gst,
            total_amount=total,
        )

    def compute(
        self,
        items: list[dict],
        other_charges: Decimal = Decimal("0"),
        tds_amount: Decimal = Decimal("0"),
        tcs_amount: Decimal = Decimal("0"),
    ) -> GSTSummary:
        """
        items: list of dicts with keys:
            description, quantity, rate, gst_rate, cess_rate,
            discount_pct, discount_amount, hsn_code (all optional except first three)
        """
        lines: list[LineItemGST] = []
        for i, item in enumerate(items, start=1):
            line = self.compute_line(
                line_no=i,
                description=item.get("description", ""),
                quantity=Decimal(str(item.get("quantity", "1"))),
                rate=Decimal(str(item.get("rate", "0"))),
                gst_rate=Decimal(str(item.get("gst_rate", "0"))),
                cess_rate=Decimal(str(item.get("cess_rate", "0"))),
                discount_pct=Decimal(str(item.get("discount_pct", "0"))),
                discount_amount=Decimal(str(item.get("discount_amount", "0"))),
                hsn_code=str(item.get("hsn_code", "")),
            )
            lines.append(line)

        subtotal = sum(l.quantity * l.rate for l in lines)
        total_discount = sum(l.discount_amount for l in lines)
        total_taxable = sum(l.taxable_amount for l in lines)
        total_cgst = sum(l.cgst_amount for l in lines)
        total_sgst = sum(l.sgst_amount for l in lines)
        total_igst = sum(l.igst_amount for l in lines)
        total_cess = sum(l.cess_amount for l in lines)
        total_gst = total_cgst + total_sgst + total_igst + total_cess

        before_round = total_taxable + total_gst + other_charges - tds_amount + tcs_amount
        grand_total_rounded = _r(before_round, 0)          # round to nearest rupee
        round_off = grand_total_rounded - _r(before_round)

        # HSN-wise summary
        hsn_map: dict[str, dict] = {}
        for l in lines:
            key = l.hsn_code or "MISC"
            if key not in hsn_map:
                hsn_map[key] = {
                    "hsn_code": key,
                    "taxable_amount": Decimal("0"),
                    "cgst": Decimal("0"),
                    "sgst": Decimal("0"),
                    "igst": Decimal("0"),
                    "cess": Decimal("0"),
                    "total": Decimal("0"),
                }
            hsn_map[key]["taxable_amount"] += l.taxable_amount
            hsn_map[key]["cgst"] += l.cgst_amount
            hsn_map[key]["sgst"] += l.sgst_amount
            hsn_map[key]["igst"] += l.igst_amount
            hsn_map[key]["cess"] += l.cess_amount
            hsn_map[key]["total"] += l.total_amount

        return GSTSummary(
            subtotal=_r(subtotal),
            total_discount=_r(total_discount),
            total_taxable=_r(total_taxable),
            total_cgst=_r(total_cgst),
            total_sgst=_r(total_sgst),
            total_igst=_r(total_igst),
            total_cess=_r(total_cess),
            total_gst=_r(total_gst),
            other_charges=_r(other_charges),
            round_off=_r(round_off),
            grand_total=grand_total_rounded,
            lines=lines,
            hsn_summary=list(hsn_map.values()),
        )


def amount_in_words(amount: Decimal) -> str:
    """Convert amount to Indian words (e.g. 1,23,456.78 → 'One Lakh...')"""
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def _convert_chunk(n: int) -> str:
        if n == 0:
            return ""
        elif n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")
        else:
            return ones[n // 100] + " Hundred" + (" " + _convert_chunk(n % 100) if n % 100 else "")

    total_paise = int(round(float(amount) * 100))
    rupees, paise = divmod(total_paise, 100)

    if rupees == 0:
        rupee_str = "Zero"
    else:
        crore = rupees // 10_000_000
        lakh = (rupees % 10_000_000) // 100_000
        thousand = (rupees % 100_000) // 1_000
        rest = rupees % 1_000
        parts = []
        if crore:
            parts.append(_convert_chunk(crore) + " Crore")
        if lakh:
            parts.append(_convert_chunk(lakh) + " Lakh")
        if thousand:
            parts.append(_convert_chunk(thousand) + " Thousand")
        if rest:
            parts.append(_convert_chunk(rest))
        rupee_str = " ".join(parts)

    result = rupee_str + " Rupees"
    if paise:
        result += " and " + _convert_chunk(paise) + " Paise"
    return result + " Only"
