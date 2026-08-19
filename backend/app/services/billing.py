"""VyaparPro – Billing Service Layer"""
from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AlreadyExistsError, BusinessError, NotFoundError
from app.db.models.billing import (
    DeliveryChallan, DeliveryChallanItem, Invoice, InvoiceItem,
    JobOrder, JobOrderItem, Payment, PaymentAllocation,
    PurchaseOrder, PurchaseOrderItem, Quotation, QuotationItem,
)
from app.db.repositories.billing import (
    DeliveryChallanRepository, DocumentSequenceRepository,
    GoodsReceiptNoteRepository, InvoiceRepository, JobOrderRepository,
    PaymentRepository, PurchaseOrderRepository, QuotationRepository,
)
from app.schemas.billing import (
    DeliveryChallanCreate, InvoiceCreate, InvoiceUpdate,
    JobOrderCreate, JobOrderUpdate, PaymentCreate,
    PurchaseOrderCreate, QuotationCreate,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.utils.gst_calculator import GSTCalculator


# ═══════════════════════════════════════════════════════════════════
# TDS ENGINE — shared by PurchaseOrderService (vendor deducts-from-you)
# and InvoiceService (customer deducts-from-you). Section thresholds
# per the Income-tax Act; "excess" = TDS only on amount crossing the
# threshold (194Q); "full" = TDS on the entire cumulative amount once
# crossed (194C/194J/194H/194I/194A), matching Tally/Zoho Books.
# ═══════════════════════════════════════════════════════════════════
TDS_SECTION_RULES = {
    "194Q": {"threshold": Decimal("5000000"), "mode": "excess"},
    "194C": {"threshold": Decimal("100000"),  "mode": "full"},
    "194J": {"threshold": Decimal("30000"),   "mode": "full"},
    "194H": {"threshold": Decimal("15000"),   "mode": "full"},
    "194I": {"threshold": Decimal("240000"),  "mode": "full"},
    "194A": {"threshold": Decimal("5000"),    "mode": "full"},
}


def _financial_year_bounds(on_date: date) -> tuple[date, date]:
    """Indian FY: 1 Apr – 31 Mar."""
    if on_date.month >= 4:
        return date(on_date.year, 4, 1), date(on_date.year + 1, 3, 31)
    return date(on_date.year - 1, 4, 1), date(on_date.year, 3, 31)


def _calc_tds_amount(party, prior_ytd: Decimal, current_taxable: Decimal) -> Decimal:
    """Given a Party (vendor or customer) with a TDS profile, the taxable value already
    transacted this FY (excluding this transaction), and this transaction's taxable value,
    return the TDS amount applicable on THIS transaction."""
    if not party or not party.tds_applicable or not party.tds_rate:
        return Decimal("0")
    rule = TDS_SECTION_RULES.get(party.tds_section, {"threshold": Decimal("0"), "mode": "full"})
    new_cumulative = prior_ytd + current_taxable
    if new_cumulative <= rule["threshold"]:
        return Decimal("0")
    if rule["mode"] == "excess":
        already_over = max(prior_ytd - rule["threshold"], Decimal("0"))
        taxable_for_tds = current_taxable - already_over if prior_ytd < rule["threshold"] else current_taxable
        taxable_for_tds = min(max(taxable_for_tds, Decimal("0")), current_taxable)
    else:
        taxable_for_tds = current_taxable
    return round(taxable_for_tds * party.tds_rate / Decimal("100"), 2)


def _calc_items(items_in: list[Any], supply_type: str):
    calc = GSTCalculator(supply_type=supply_type)
    results = []
    subtotal = Decimal("0")
    disc_total = Decimal("0")
    taxable_total = Decimal("0")
    cgst_total = Decimal("0")
    sgst_total = Decimal("0")
    igst_total = Decimal("0")
    cess_total = Decimal("0")
    grand_total = Decimal("0")

    for i, item in enumerate(items_in):
        line = calc.compute_line(
            line_no=i + 1,
            description=item.description,
            quantity=item.quantity,
            rate=item.rate,
            gst_rate=item.gst_rate,
            cess_rate=item.cess_rate,
            discount_pct=item.discount_pct,
            discount_amount=item.discount_amount,
            hsn_code=item.hsn_code or "",
        )
        results.append(line)
        subtotal += line.quantity * line.rate
        disc_total += line.discount_amount
        taxable_total += line.taxable_amount
        cgst_total += line.cgst_amount
        sgst_total += line.sgst_amount
        igst_total += line.igst_amount
        cess_total += line.cess_amount
        grand_total += line.total_amount

    return results, {
        "subtotal": subtotal, "discount_amount": disc_total,
        "taxable_amount": taxable_total, "cgst_amount": cgst_total,
        "sgst_amount": sgst_total, "igst_amount": igst_total,
        "cess_amount": cess_total,
    }


class QuotationService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = QuotationRepository(session)
        self.seq = DocumentSequenceRepository(session)
        self.session = session

    async def get_pdf_data(self, quote_id: UUID, company_id: UUID) -> bytes:
        from app.utils.pdf_generator import PDFDocumentData, generate_invoice_pdf
        from app.db.repositories import CompanyRepository
        q = await self.repo.get_detail(quote_id)
        if not q:
            raise NotFoundError("Quotation not found.")
        company = await CompanyRepository(self.session).get(company_id)
        items_data = [{
            "line_no": i + 1, "description": it.description, "hsn_code": it.hsn_code or "",
            "quantity": str(it.quantity), "rate": it.rate, "discount_amount": it.discount_amount,
            "taxable_amount": it.taxable_amount, "gst_rate": it.gst_rate,
            "cgst_amount": it.cgst_amount, "sgst_amount": it.sgst_amount, "igst_amount": it.igst_amount,
            "total_amount": it.total_amount,
        } for i, it in enumerate(q.items)]
        data = PDFDocumentData(
            doc_type="quotation", doc_no=q.quote_no, doc_date=q.quote_date, due_date=q.valid_until,
            company_name=company.legal_name if company else "", company_gstin=(company.gstin or "") if company else "",
            company_tagline=((company.settings or {}).get("tagline", "") if company else ""),
            company_address=(company.reg_address or "") if company else "",
            company_phone=(company.phone or "") if company else "", company_email=(company.email or "") if company else "",
            company_pan=(company.pan or "") if company else "", company_logo_url=(company.logo_url or "") if company else "",
            bank_name=(company.settings or {}).get("bank_name", "") if company else "",
            bank_branch=(company.settings or {}).get("bank_branch", "") if company else "",
            bank_account_no=(company.settings or {}).get("bank_account_no", "") if company else "",
            bank_ifsc=(company.settings or {}).get("bank_ifsc", "") if company else "",
            upi_id=(company.settings or {}).get("upi_id", "") if company else "",
            terms_conditions=q.terms_conditions or ((company.settings or {}).get("default_terms", "") if company else ""),
            party_name=q.billing_name, party_gstin=q.billing_gstin or "", party_address=q.billing_address or "",
            party_phone=q.contact_phone or ((q.party.phone or "") if q.party else ""),
            place_of_supply=q.place_of_supply, supply_type=q.supply_type, items=items_data,
            subtotal=q.subtotal, discount_amount=q.discount_amount, taxable_amount=q.taxable_amount,
            cgst_amount=q.cgst_amount, sgst_amount=q.sgst_amount, igst_amount=q.igst_amount,
            cess_amount=q.cess_amount, round_off=q.round_off, total_amount=q.total_amount,
            notes=q.notes or "",
        )
        return generate_invoice_pdf(data)

    async def create(self, company_id: UUID, payload: QuotationCreate, user_id: UUID) -> Quotation:
        lines, totals = _calc_items(payload.items, payload.supply_type)
        total = totals["taxable_amount"] + totals["cgst_amount"] + totals["sgst_amount"] + totals["igst_amount"] + totals["cess_amount"] + payload.other_charges - payload.tds_amount
        quote_no = await self.seq.next_number(company_id, "quote")
        quote = await self.repo.create({
            "company_id": company_id,
            "quote_no": quote_no,
            "quote_date": payload.quote_date,
            "valid_until": payload.valid_until,
            "party_id": payload.party_id,
            "billing_name": payload.billing_name,
            "billing_gstin": payload.billing_gstin,
            "billing_address": payload.billing_address,
            "billing_state_code": payload.billing_state_code,
            "place_of_supply": payload.place_of_supply,
            "supply_type": payload.supply_type,
            "other_charges": payload.other_charges,
            "tds_amount": payload.tds_amount,
            "notes": payload.notes,
            "terms_conditions": payload.terms_conditions,
            "warehouse_id": payload.warehouse_id,
            "payment_terms": payload.payment_terms,
            "created_by": user_id,
            "status": "draft",
            **totals,
            "total_amount": total,
        })
        for line in lines:
            item = payload.items[line.line_no - 1]
            self.session.add(QuotationItem(
                quotation_id=quote.id,
                product_id=item.product_id,
                description=line.description,
                hsn_code=line.hsn_code,
                quantity=line.quantity,
                uom_id=item.uom_id,
                rate=line.rate,
                discount_pct=line.discount_pct,
                discount_amount=line.discount_amount,
                taxable_amount=line.taxable_amount,
                gst_rate=line.gst_rate,
                cgst_amount=line.cgst_amount,
                sgst_amount=line.sgst_amount,
                igst_amount=line.igst_amount,
                cess_amount=line.cess_amount,
                total_amount=line.total_amount,
                display_order=item.display_order,
            ))
        await self.session.flush()
        return await self.repo.get_detail(quote.id)

    async def convert_to_invoice(self, quote_id: UUID, company_id: UUID, user_id: UUID) -> Invoice:
        quote = await self.repo.get_detail(quote_id)
        if not quote:
            raise NotFoundError("Quotation not found.")
        if quote.status not in ("draft", "sent", "accepted"):
            raise BusinessError("Quotation cannot be converted in current status.")
        inv_svc = InvoiceService(self.session)
        from app.schemas.billing import BillingItemIn, InvoiceCreate
        items_in = [
            BillingItemIn(
                product_id=it.product_id, description=it.description,
                hsn_code=it.hsn_code, quantity=it.quantity, uom_id=it.uom_id,
                rate=it.rate, discount_pct=it.discount_pct, gst_rate=it.gst_rate,
                display_order=it.display_order,
            )
            for it in quote.items
        ]
        inv_payload = InvoiceCreate(
            invoice_type="tax_invoice",
            invoice_date=date.today(),
            party_id=quote.party_id,
            billing_name=quote.billing_name,
            billing_gstin=quote.billing_gstin,
            billing_address=quote.billing_address,
            billing_state_code=quote.billing_state_code,
            place_of_supply=quote.place_of_supply,
            supply_type=quote.supply_type,
            quote_id=quote.id,
            other_charges=quote.other_charges,
            notes=quote.notes,
            items=items_in,
        )
        inv = await inv_svc.create(company_id, inv_payload, user_id)
        await self.repo.update(quote, {"status": "converted", "converted_to_invoice_id": inv.id})
        return inv


class JobOrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = JobOrderRepository(session)
        self.seq = DocumentSequenceRepository(session)
        self.session = session

    async def create(self, company_id: UUID, payload: JobOrderCreate, user_id: UUID) -> JobOrder:
        lines, totals = _calc_items(payload.items, "intra")
        total = totals["taxable_amount"] + totals["cgst_amount"] + totals["sgst_amount"] + totals["igst_amount"] + totals["cess_amount"] + payload.other_charges
        jo_no = await self.seq.next_number(company_id, "jo")
        jo = await self.repo.create({
            "company_id": company_id,
            "jo_no": jo_no,
            "jo_date": payload.jo_date,
            "party_id": payload.party_id,
            "billing_name": payload.billing_name,
            "jo_type": payload.jo_type,
            "title": payload.title,
            "description": payload.description,
            "scope_of_work": payload.scope_of_work,
            "priority": payload.priority,
            "linked_po_id": payload.linked_po_id,
            "linked_quote_id": payload.linked_quote_id,
            "start_date": payload.start_date,
            "expected_completion": payload.expected_completion,
            "estimated_amount": payload.estimated_amount,
            "assigned_to": payload.assigned_to,
            "notes": payload.notes,
            "created_by": user_id,
            "status": "open",
            **totals,
            "total_amount": total,
        })
        for line in lines:
            item = payload.items[line.line_no - 1]
            self.session.add(JobOrderItem(
                jo_id=jo.id,
                product_id=item.product_id,
                description=line.description,
                item_type="service",
                quantity=line.quantity,
                uom_id=item.uom_id,
                rate=line.rate,
                gst_rate=line.gst_rate,
                amount=line.total_amount,
                warehouse_id=item.warehouse_id,
                display_order=item.display_order,
            ))
        await self.session.flush()
        return await self.repo.get_detail(jo.id)

    async def convert_to_invoice(self, jo_id: UUID, company_id: UUID, user_id: UUID) -> Invoice:
        jo = await self.repo.get_detail(jo_id)
        if not jo:
            raise NotFoundError("Job Order not found.")
        inv_svc = InvoiceService(self.session)
        from app.schemas.billing import BillingItemIn, InvoiceCreate
        items_in = [
            BillingItemIn(
                product_id=it.product_id, description=it.description,
                quantity=it.quantity, uom_id=it.uom_id, rate=it.rate,
                gst_rate=it.gst_rate, jo_item_id=it.id, display_order=it.display_order,
            )
            for it in jo.items
        ]
        inv_payload = InvoiceCreate(
            invoice_type="tax_invoice", invoice_date=date.today(),
            party_id=jo.party_id, billing_name=jo.billing_name,
            jo_id=jo.id, jo_no=jo.jo_no,
            place_of_supply="27", supply_type="intra",
            items=items_in,
        )
        inv = await inv_svc.create(company_id, inv_payload, user_id)
        await self.repo.update(jo, {"status": "invoiced"})
        return inv


class PurchaseOrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = PurchaseOrderRepository(session)
        self.seq = DocumentSequenceRepository(session)
        self.session = session

    async def get_pdf_data(self, po_id: UUID, company_id: UUID) -> bytes:
        from app.utils.pdf_generator import PDFDocumentData, generate_purchase_order_pdf
        from app.db.repositories import CompanyRepository, PartyRepository
        po = await self.repo.get_detail(po_id)
        if not po:
            raise NotFoundError("Purchase order not found.")
        company = await CompanyRepository(self.session).get(company_id)
        vendor = await PartyRepository(self.session).get(po.vendor_id) if po.vendor_id else None
        from app.db.repositories import UnitOfMeasureRepository, ProductRepository
        uom_repo = UnitOfMeasureRepository(self.session)
        product_repo = ProductRepository(self.session)

        # Resolve each line's unit: use the line's own uom_id if set, else
        # fall back to the linked product's own default unit of measure.
        product_uom_cache: dict = {}
        resolved_uom_ids = []
        for it in po.items:
            uid = it.uom_id
            if not uid and it.product_id:
                if it.product_id not in product_uom_cache:
                    prod = await product_repo.get(it.product_id)
                    product_uom_cache[it.product_id] = prod.uom_id if prod else None
                uid = product_uom_cache[it.product_id]
            resolved_uom_ids.append(uid)

        uom_names = {}
        for uid in set(u for u in resolved_uom_ids if u):
            uom = await uom_repo.get(uid)
            if uom:
                uom_names[uid] = uom.uom_code or uom.uom_name

        items_data = [{
            "line_no": i + 1, "description": it.description, "hsn_code": it.hsn_code or "",
            "unit": uom_names.get(resolved_uom_ids[i], ""),
            "quantity": str(it.quantity), "rate": it.rate, "discount_amount": it.discount_amount,
            "taxable_amount": it.taxable_amount, "gst_rate": it.gst_rate,
            "cgst_amount": it.cgst_amount, "sgst_amount": it.sgst_amount, "igst_amount": it.igst_amount,
            "total_amount": it.amount,
        } for i, it in enumerate(po.items)]
        data = PDFDocumentData(
            doc_type="po", doc_no=po.po_no, doc_date=po.po_date,
            company_name=company.legal_name if company else "", company_gstin=(company.gstin or "") if company else "",
            company_tagline=((company.settings or {}).get("tagline", "") if company else ""),
            company_address=(company.reg_address or "") if company else "",
            company_phone=(company.phone or "") if company else "", company_email=(company.email or "") if company else "",
            company_pan=(company.pan or "") if company else "", company_logo_url=(company.logo_url or "") if company else "",
            party_name=vendor.display_name if vendor else "", party_gstin=(vendor.gstin or "") if vendor else "",
            party_address=(vendor.billing_address or "") if vendor else "",
            party_phone=(vendor.phone or "") if vendor else "",
            place_of_supply=(vendor.billing_state_code or "") if vendor else "",
            bank_name=(company.settings or {}).get("bank_name", "") if company else "",
            bank_branch=(company.settings or {}).get("bank_branch", "") if company else "",
            bank_account_no=(company.settings or {}).get("bank_account_no", "") if company else "",
            bank_ifsc=(company.settings or {}).get("bank_ifsc", "") if company else "",
            upi_id=(company.settings or {}).get("upi_id", "") if company else "",
            terms_conditions=(po.warranty_terms or "") or ((company.settings or {}).get("po_terms_conditions", "") if company else ""),
            items=items_data, subtotal=po.subtotal, taxable_amount=po.taxable_amount,
            cgst_amount=po.cgst_amount, sgst_amount=po.sgst_amount, igst_amount=po.igst_amount,
            total_amount=po.total_amount, notes=po.notes or "",
            expected_delivery=po.expected_delivery, delivery_address=po.delivery_address or "",
            supplier_ref=po.vendor_ref_no or "", payment_terms=po.payment_terms or "",
            delivery_terms=po.delivery_terms or "", remarks=po.special_instructions or po.notes or "",
            buyer_contact=(company.settings or {}).get("contact_person", "") if company else "",
            status=po.status or "draft",
        )
        return generate_purchase_order_pdf(data)

    async def get_return_pdf_data(self, po_id: UUID, jv_id: UUID, company_id: UUID) -> bytes:
        from app.utils.pdf_generator import PDFDocumentData, generate_invoice_pdf
        from app.db.repositories import CompanyRepository, PartyRepository
        from app.db.models.accounting import JournalVoucher
        from app.db.models.billing import PurchaseOrderItem
        from app.db.models.inventory import StockMovement

        jv = await self.session.get(JournalVoucher, jv_id)
        if not jv or jv.company_id != company_id or jv.ref_type != "purchase_order" or str(jv.ref_id) != str(po_id):
            raise NotFoundError("Purchase return not found.")

        po = await self.repo.get_or_raise_scoped(po_id, company_id=company_id)
        company = await CompanyRepository(self.session).get(company_id)
        vendor = await PartyRepository(self.session).get(po.vendor_id) if po.vendor_id else None

        mv_result = await self.session.execute(
            select(StockMovement).where(
                StockMovement.ref_type == "purchase_return_voucher",
                StockMovement.ref_id == jv_id,
            )
        )
        movements = mv_result.scalars().all()

        po_items_result = await self.session.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po_id)
        )
        po_items = {str(it.product_id): it for it in po_items_result.scalars().all() if it.product_id}

        items_data = []
        total_taxable = Decimal("0"); total_cgst = Decimal("0")
        total_sgst = Decimal("0"); total_igst = Decimal("0")
        for i, m in enumerate(movements):
            it = po_items.get(str(m.product_id))
            qty = abs(m.quantity)
            rate = m.cost_price or (it.rate if it else Decimal("0"))
            gst_rate = it.gst_rate if it else Decimal("0")
            ratio = (qty / it.quantity) if it and it.quantity else Decimal("0")
            line_taxable = qty * rate
            line_cgst = (it.cgst_amount * ratio) if it else Decimal("0")
            line_sgst = (it.sgst_amount * ratio) if it else Decimal("0")
            line_igst = (it.igst_amount * ratio) if it else Decimal("0")
            total_taxable += line_taxable; total_cgst += line_cgst
            total_sgst += line_sgst; total_igst += line_igst
            items_data.append({
                "line_no": i + 1, "description": it.description if it else str(m.product_id),
                "hsn_code": it.hsn_code if it else "", "quantity": str(qty), "rate": rate,
                "taxable_amount": line_taxable, "gst_rate": gst_rate,
                "cgst_amount": line_cgst, "sgst_amount": line_sgst, "igst_amount": line_igst,
                "total_amount": line_taxable + line_cgst + line_sgst + line_igst,
            })

        data = PDFDocumentData(
            doc_type="purchase_return", doc_no=jv.jv_no, doc_date=jv.jv_date,
            company_name=company.legal_name if company else "", company_gstin=(company.gstin or "") if company else "",
            company_tagline=((company.settings or {}).get("tagline", "") if company else ""),
            company_address=(company.reg_address or "") if company else "",
            company_phone=(company.phone or "") if company else "", company_email=(company.email or "") if company else "",
            company_pan=(company.pan or "") if company else "", company_logo_url=(company.logo_url or "") if company else "",
            party_name=vendor.display_name if vendor else "", party_gstin=(vendor.gstin or "") if vendor else "",
            party_address=(vendor.billing_address or "") if vendor else "",
            party_phone=(vendor.phone or "") if vendor else "",
            po_no=po.po_no, po_date=po.po_date, items=items_data,
            taxable_amount=total_taxable, cgst_amount=total_cgst, sgst_amount=total_sgst,
            igst_amount=total_igst, total_amount=jv.total_debit,
        )
        return generate_invoice_pdf(data)

    # Section-wise TDS threshold rules (Income-tax Act). "excess" = TDS only on the amount
    # crossing the threshold (194Q); "full" = once threshold is crossed, TDS applies on the
    # ENTIRE cumulative amount incl. this transaction (194C/194J/194H/194I/194A), per common
    # ERP practice (Tally/Zoho Books) and CBDT clarification for 194C.
    async def _calc_tds(self, company_id: UUID, vendor, po_date: date, current_taxable: Decimal) -> Decimal:
        if not vendor or not vendor.tds_applicable:
            return Decimal("0")
        fy_start, fy_end = _financial_year_bounds(po_date)
        prior_ytd = await self.repo.sum_taxable_for_vendor_in_fy(company_id, vendor.id, fy_start, fy_end)
        return _calc_tds_amount(vendor, prior_ytd, current_taxable)

    async def create(self, company_id: UUID, payload: PurchaseOrderCreate, user_id: UUID) -> PurchaseOrder:
        lines, totals = _calc_items(payload.items, payload.supply_type)
        total = totals["taxable_amount"] + totals["cgst_amount"] + totals["sgst_amount"] + totals["igst_amount"] + totals["cess_amount"] + payload.other_charges

        # TDS is auto-derived from the vendor's TDS profile + section threshold, calculated on
        # the taxable value only (GST is excluded from the TDS base — CBDT Circular 23/2017).
        from app.db.repositories import PartyRepository
        vendor = await PartyRepository(self.session).get(payload.vendor_id)
        tds_amount = await self._calc_tds(company_id, vendor, payload.po_date, totals["taxable_amount"])

        branch_code = None
        if payload.branch_id:
            from app.db.repositories import BranchRepository
            branch = await BranchRepository(self.session).get(payload.branch_id)
            branch_code = branch.branch_code if branch else None
        po_no = await self.seq.next_number(company_id, "po", branch_id=payload.branch_id, branch_code=branch_code)
        po = await self.repo.create({
            "company_id": company_id,
            "po_no": po_no,
            "po_date": payload.po_date,
            "vendor_id": payload.vendor_id,
            "vendor_ref_no": payload.vendor_ref_no,
            "linked_jo_id": payload.linked_jo_id,
            "branch_id": payload.branch_id,
            "deliver_to_warehouse_id": payload.deliver_to_warehouse_id,
            "expected_delivery": payload.expected_delivery,
            "currency": payload.currency,
            "payment_terms": payload.payment_terms,
            "delivery_terms": payload.delivery_terms,
            "special_instructions": payload.special_instructions,
            "notes": payload.notes,
            "other_charges": payload.other_charges,
            "tds_amount": tds_amount,
            "created_by": user_id,
            "status": "open",
            "approval_status": "pending",
            "reverse_charge": payload.reverse_charge,
            **totals,
            "total_amount": total,
        })
        from app.db.repositories import ProductRepository
        product_repo = ProductRepository(self.session)
        product_uom_cache: dict = {}
        for line in lines:
            item = payload.items[line.line_no - 1]
            uom_id = item.uom_id
            if not uom_id and item.product_id:
                if item.product_id not in product_uom_cache:
                    prod = await product_repo.get(item.product_id)
                    product_uom_cache[item.product_id] = prod.uom_id if prod else None
                uom_id = product_uom_cache[item.product_id]
            self.session.add(PurchaseOrderItem(
                po_id=po.id,
                product_id=item.product_id,
                description=line.description,
                hsn_code=line.hsn_code,
                quantity=line.quantity,
                uom_id=uom_id,
                rate=line.rate,
                discount_pct=line.discount_pct,
                discount_amount=line.discount_amount,
                taxable_amount=line.taxable_amount,
                gst_rate=line.gst_rate,
                cgst_amount=line.cgst_amount,
                sgst_amount=line.sgst_amount,
                igst_amount=line.igst_amount,
                cess_amount=line.cess_amount,
                amount=line.total_amount,
                total_amount=line.total_amount,
                display_order=item.display_order,
                itc_eligible=item.itc_eligible,
                itc_ineligible_reason=None if item.itc_eligible else item.itc_ineligible_reason,
            ))
        await self.session.flush()
        return await self.repo.get_detail(po.id)
    
    async def receive(self, po_id: UUID, company_id: UUID, user_id: UUID,
                       received_items: list[dict] | None = None) -> PurchaseOrder:
        """Mark goods received against a PO and add the qty to stock. Defaults to full receipt."""
        po = await self.repo.get_detail(po_id)
        if not po:
            raise NotFoundError("Purchase order not found.")
        if po.status in ("received", "cancelled", "closed"):
            raise BusinessError("Purchase order already received or closed.")

        wh_id = po.deliver_to_warehouse_id
        if not wh_id:
            from app.db.repositories.inventory import WarehouseRepository
            default_wh = await WarehouseRepository(self.session).get_default(company_id)
            wh_id = default_wh.id if default_wh else None
        if not wh_id:
            raise BusinessError("No delivery warehouse set on this PO and no default warehouse configured.")

        from app.services.inventory import InventoryService
        inv_svc = InventoryService(self.session)
        override = {str(r["item_id"]): Decimal(str(r["qty"])) for r in (received_items or [])}
        is_partial_request = received_items is not None

        total_taxable = Decimal("0")
        total_cgst = Decimal("0")
        total_sgst = Decimal("0")
        total_igst = Decimal("0")
        total_value = Decimal("0")

        for item in po.items:
            if not item.product_id:
                continue
            if is_partial_request:
                # A partial-receive request was made explicitly — any item NOT
                # listed means the user entered 0 for it, so default to 0, not
                # "receive everything remaining."
                qty = override.get(str(item.id), Decimal("0"))
            else:
                # No item list at all (the "Receive All Goods" button) — every
                # item defaults to its full remaining quantity, as before.
                qty = item.quantity - item.received_qty
            if qty <= 0:
                continue
            await inv_svc.record_movement(
                company_id=company_id, product_id=item.product_id, warehouse_id=wh_id,
                movement_type="purchase", quantity=qty, cost_price=item.rate,
                ref_type="purchase_order", ref_id=po.id, ref_no=po.po_no,
                narration=f"Goods received against PO {po.po_no}", user_id=user_id,
            )
            item.received_qty = item.received_qty + qty

            # NEW — accumulate only the VALUE of what was actually received this call,
            # prorated from the line's full-quantity totals (partial receipt safe)
            proportion = qty / item.quantity if item.quantity else Decimal("0")
            total_taxable += item.taxable_amount * proportion
            total_cgst    += item.cgst_amount * proportion
            total_sgst    += item.sgst_amount * proportion
            total_igst    += item.igst_amount * proportion
            total_value   += item.total_amount * proportion

        # NEW — post to Ledger & Books: Dr Purchase + Dr GST Input, Cr Sundry Creditors
        if total_taxable > 0:
            from app.services.accounting import AutoAccountingService
            auto = AutoAccountingService(self.session)
            await auto.on_purchase_bill_created(
                company_id=company_id, bill_id=po.id, bill_no=po.po_no,
                bill_date=date.today(), vendor_id=po.vendor_id,
                taxable_amount=total_taxable, cgst_amount=total_cgst,
                sgst_amount=total_sgst, igst_amount=total_igst,
                total_amount=total_value, user_id=user_id,
                tds_amount=po.tds_amount,
            )

        all_received = all(it.received_qty >= it.quantity for it in po.items if it.product_id)
        await self.repo.update(po, {
            "status": "received" if all_received else "partially_received",
            "actual_delivery": date.today(),
        })
        await self.session.flush()
        return await self.repo.get_detail(po_id)

    async def return_goods(self, po_id: UUID, company_id: UUID, user_id: UUID,
                            returned_items: list[dict]) -> PurchaseOrder:
        po = await self.repo.get_detail(po_id)
        if not po:
            raise NotFoundError("Purchase order not found.")

        wh_id = po.deliver_to_warehouse_id
        if not wh_id:
            from app.db.repositories.inventory import WarehouseRepository
            default_wh = await WarehouseRepository(self.session).get_default(company_id)
            wh_id = default_wh.id if default_wh else None
        if not wh_id:
            raise BusinessError("No delivery warehouse set on this PO and no default warehouse configured.")

        override = {str(r["item_id"]): Decimal(str(r["qty"])) for r in returned_items}
        items_by_id = {str(it.id): it for it in po.items}

        for item_id, qty in override.items():
            item = items_by_id.get(item_id)
            if not item:
                raise BusinessError(f"Item {item_id} does not belong to this purchase order.")
            if qty < 0:
                raise BusinessError("Returned quantity cannot be negative.")
            returnable = item.received_qty - item.returned_qty
            if qty > returnable:
                raise BusinessError(
                    f"Cannot return {qty} of '{item.description}' — only {returnable} available to return."
                )

        total_taxable = Decimal("0")
        total_cgst = Decimal("0")
        total_sgst = Decimal("0")
        total_igst = Decimal("0")
        total_value = Decimal("0")
        lines_to_move = []

        for item_id, qty in override.items():
            if qty <= 0:
                continue
            item = items_by_id[item_id]
            if not item.product_id:
                continue
            lines_to_move.append((item, qty))
            item.returned_qty = item.returned_qty + qty

            proportion = qty / item.quantity if item.quantity else Decimal("0")
            total_taxable += item.taxable_amount * proportion
            total_cgst    += item.cgst_amount * proportion
            total_sgst    += item.sgst_amount * proportion
            total_igst    += item.igst_amount * proportion
            total_value   += item.total_amount * proportion

        if not lines_to_move:
            raise BusinessError("Nothing to return.")

        # Post the ledger entry FIRST so every stock movement below can be tagged
        # with this exact voucher's id — that's what makes a later, precise
        # "undo just this return" possible.
        from app.services.accounting import AutoAccountingService
        auto = AutoAccountingService(self.session)
        jv = await auto.on_purchase_return_created(
            company_id=company_id, return_ref_id=po.id, return_ref_no=po.po_no,
            return_date=date.today(), vendor_id=po.vendor_id,
            taxable_amount=total_taxable, cgst_amount=total_cgst,
            sgst_amount=total_sgst, igst_amount=total_igst,
            total_amount=total_value, user_id=user_id,
        )

        from app.services.inventory import InventoryService
        inv_svc = InventoryService(self.session)
        for item, qty in lines_to_move:
            await inv_svc.record_movement(
                company_id=company_id, product_id=item.product_id, warehouse_id=wh_id,
                movement_type="purchase_return", quantity=-qty, cost_price=item.rate,
                ref_type="purchase_return_voucher", ref_id=jv.id, ref_no=jv.jv_no,
                narration=f"Goods returned against PO {po.po_no}", user_id=user_id,
            )

        await self.session.flush()
        return await self.repo.get_detail(po_id)

    async def delete_return(self, po_id: UUID, jv_id: UUID, company_id: UUID, user_id: UUID) -> PurchaseOrder:
        """Undo one specific past purchase return: restores stock, rolls back returned_qty, reverses its ledger entry."""
        po = await self.repo.get_detail(po_id)
        if not po:
            raise NotFoundError("Purchase order not found.")

        from app.db.models.accounting import JournalVoucher
        jv = await self.session.get(JournalVoucher, jv_id)
        if not jv or jv.company_id != company_id or jv.ref_type != "purchase_order" or str(jv.ref_id) != str(po_id):
            raise NotFoundError("Purchase return voucher not found for this PO.")
        if jv.is_reversed:
            raise BusinessError("This return has already been reversed.")

        from app.db.models.inventory import StockMovement
        result = await self.session.execute(
            select(StockMovement).where(
                StockMovement.ref_type == "purchase_return_voucher",
                StockMovement.ref_id == jv_id,
            )
        )
        movements = result.scalars().all()
        if not movements:
            raise BusinessError("Could not find the stock movements for this return — it may predate this feature.")

        from app.services.inventory import InventoryService
        inv_svc = InventoryService(self.session)
        items_by_product = {str(it.product_id): it for it in po.items if it.product_id}

        for m in movements:
            await inv_svc.record_movement(
                company_id=company_id, product_id=m.product_id, warehouse_id=m.warehouse_id,
                movement_type="purchase_return_undo", quantity=-m.quantity,  # m.quantity was negative
                ref_type="purchase_order", ref_id=po.id, ref_no=po.po_no,
                narration=f"Reversed return against PO {po.po_no}", user_id=user_id,
            )
            item = items_by_product.get(str(m.product_id))
            if item:
                item.returned_qty = max(Decimal("0"), item.returned_qty + m.quantity)

        from app.services.accounting import JournalVoucherService
        jv_svc = JournalVoucherService(self.session)
        await jv_svc.reverse(jv_id, company_id, user_id)

        await self.session.flush()
        return await self.repo.get_detail(po_id)


class InvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = InvoiceRepository(session)
        self.seq = DocumentSequenceRepository(session)
        self.session = session

    async def _default_warehouse_id(self, company_id: UUID):
        from app.db.repositories.inventory import WarehouseRepository
        wh = await WarehouseRepository(self.session).get_default(company_id)
        return wh.id if wh else None

    async def create(self, company_id: UUID, payload: InvoiceCreate, user_id: UUID) -> Invoice:
        # Exports are always inter-state supply under GST law — there's no such
        # thing as an intra-state export. Force it here rather than trusting
        # whatever supply_type the form happened to have selected, otherwise
        # export tax gets wrongly split into CGST/SGST instead of IGST.
        effective_supply_type = "inter" if payload.is_export else payload.supply_type
        lines, totals = _calc_items(payload.items, effective_supply_type)
        # TDS Receivable is auto-derived from the CUSTOMER's TDS profile + section threshold —
        # only applies to normal tax invoices (a credit note has nothing to withhold).
        tds_amount = Decimal("0")
        if payload.invoice_type == "tax_invoice":
            from app.db.repositories import PartyRepository
            customer = await PartyRepository(self.session).get(payload.party_id)
            if customer and customer.tds_applicable:
                fy_start, fy_end = _financial_year_bounds(payload.invoice_date)
                prior_ytd = await self.repo.sum_taxable_for_customer_in_fy(company_id, customer.id, fy_start, fy_end)
                tds_amount = _calc_tds_amount(customer, prior_ytd, totals["taxable_amount"])

        from decimal import ROUND_HALF_UP
        raw_total = (totals["taxable_amount"] + totals["cgst_amount"] + totals["sgst_amount"] +
                     totals["igst_amount"] + totals["cess_amount"] + payload.other_charges -
                     tds_amount + payload.tcs_amount)
        rounded = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        round_off = rounded - raw_total + payload.round_off
        branch_code = None
        if payload.branch_id:
            from app.db.repositories import BranchRepository
            branch = await BranchRepository(self.session).get(payload.branch_id)
            branch_code = branch.branch_code if branch else None
        inv_no = await self.seq.next_number(company_id, "invoice", branch_id=payload.branch_id, branch_code=branch_code)
        inv = await self.repo.create({
            "company_id": company_id,
            "invoice_no": inv_no,
            "invoice_type": payload.invoice_type,
            "invoice_date": payload.invoice_date,
            "due_date": payload.due_date,
            "party_id": payload.party_id,
            "billing_name": payload.billing_name,
            "billing_gstin": payload.billing_gstin,
            "billing_address": payload.billing_address,
            "billing_state_code": payload.billing_state_code,
            "shipping_name": payload.shipping_name,
            "shipping_address": payload.shipping_address,
            "contact_phone": payload.contact_phone,
            "contact_email": payload.contact_email,
            "jo_id": payload.jo_id,
            "jo_no": payload.jo_no,
            "po_id": payload.po_id,
            "po_no": payload.po_no,
            "po_date": payload.po_date,
            "transporter_name": payload.transporter_name,
            "transporter_id": payload.transporter_id,
            "vehicle_no": payload.vehicle_no,
            "quote_id": payload.quote_id,
            "dc_id": payload.dc_id,
            "against_invoice_id": payload.against_invoice_id,
            "place_of_supply": payload.place_of_supply,
            "supply_type": effective_supply_type,
            "reverse_charge": payload.reverse_charge,
            "currency": payload.currency,
            "is_export": payload.is_export,
            "export_type": payload.export_type,
            "supply_category": payload.supply_category,
            "branch_id": payload.branch_id,
            "warehouse_id": payload.warehouse_id,
            "payment_terms": payload.payment_terms,
            "notes": payload.notes,
            "terms_conditions": payload.terms_conditions,
            "other_charges": payload.other_charges,
            "tds_amount": tds_amount,
            "tcs_amount": payload.tcs_amount,
            "round_off": round_off,
            "status": "draft",
            "created_by": user_id,
            **totals,
            "total_amount": rounded,
        })
        for line in lines:
            item = payload.items[line.line_no - 1]
            is_igst = payload.supply_type == "inter"
            self.session.add(InvoiceItem(
                invoice_id=inv.id,
                product_id=item.product_id,
                description=line.description,
                hsn_code=line.hsn_code,
                sac_code=item.sac_code,
                quantity=line.quantity,
                uom_id=item.uom_id,
                rate=line.rate,
                mrp=item.mrp,
                discount_pct=line.discount_pct,
                discount_amount=line.discount_amount,
                taxable_amount=line.taxable_amount,
                gst_rate=line.gst_rate,
                cgst_rate=line.cgst_rate,
                sgst_rate=line.sgst_rate,
                igst_rate=line.igst_rate,
                cess_rate=line.cess_rate,
                cgst_amount=line.cgst_amount,
                sgst_amount=line.sgst_amount,
                igst_amount=line.igst_amount,
                cess_amount=line.cess_amount,
                total_amount=line.total_amount,
                warehouse_id=item.warehouse_id,
                batch_no=item.batch_no,
                serial_no=item.serial_no,
                jo_item_id=item.jo_item_id,
                display_order=item.display_order,
            ))
        await self.session.flush()
        return await self.repo.get_detail(inv.id)

    async def finalize(self, invoice_id: UUID, company_id: UUID, user_id: UUID) -> Invoice:
        inv = await self.repo.get_or_raise_scoped(invoice_id, company_id=company_id)
        if inv.status not in ("draft",):
            raise BusinessError("Only draft invoices can be finalized.")
        updated = await self.repo.update(inv, {
            "status": "finalized",
            "finalized_at": datetime.now(timezone.utc),
            "finalized_by": user_id,
        })

        try:
            from app.services.inventory import InventoryService
            inv_svc = InventoryService(self.session)
            result = await self.session.execute(
                select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.items))
            )
            inv_loaded = result.scalar_one()
            default_wh = None
            for item in inv_loaded.items:
                if not item.product_id:
                    continue
                wh_id = item.warehouse_id or inv.warehouse_id
                if not wh_id:
                    default_wh = default_wh or await self._default_warehouse_id(company_id)
                    wh_id = default_wh
                if not wh_id:
                    continue  # no warehouse anywhere — skip rather than crash finalize

                # NEW — a credit note (Sales Return) is goods coming BACK, so stock
                # goes UP, not down. Everything else (normal sales) behaves as before.
                is_return = inv.invoice_type == "credit_note"
                await inv_svc.record_movement(
                    company_id=company_id, product_id=item.product_id, warehouse_id=wh_id,
                    movement_type="sale_return" if is_return else "sale",
                    quantity=item.quantity if is_return else -item.quantity,
                    ref_type="invoice", ref_id=inv.id, ref_no=inv.invoice_no,
                    narration=f"Sales return via {inv.invoice_no}" if is_return else f"Sale via invoice {inv.invoice_no}",
                    user_id=user_id,
                )
        except Exception as e:
            import traceback
            print("STOCK DEDUCTION FAILED:", e)
            traceback.print_exc() 

        # Trigger auto-accounting
        try:
            from app.services.accounting import AutoAccountingService
            auto = AutoAccountingService(self.session)
            await auto.on_invoice_finalized(
                company_id=company_id, invoice_id=invoice_id,
                invoice_no=inv.invoice_no, invoice_date=inv.invoice_date,
                party_id=inv.party_id, taxable_amount=inv.taxable_amount,
                cgst_amount=inv.cgst_amount, sgst_amount=inv.sgst_amount,
                igst_amount=inv.igst_amount, total_amount=inv.total_amount,
                supply_type=inv.supply_type, user_id=user_id,
                invoice_type=inv.invoice_type,
                tds_amount=inv.tds_amount,
            )
        except Exception:
            pass  # Accounting optional at this stage
        return updated

    async def cancel(self, invoice_id: UUID, company_id: UUID, reason: str, user_id: UUID) -> Invoice:
        inv = await self.repo.get_or_raise_scoped(invoice_id, company_id=company_id)
        if inv.status in ("cancelled", "void"):
            raise BusinessError("Invoice is already cancelled.")
        if inv.paid_amount > 0:
            raise BusinessError("Cannot cancel a partially/fully paid invoice.")
        if inv.status != "draft":
            try:
                from app.services.inventory import InventoryService
                inv_svc = InventoryService(self.session)
                result = await self.session.execute(
                    select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.items))
                )
                inv_loaded = result.scalar_one()
                default_wh = None
                for item in inv_loaded.items:
                    if not item.product_id:
                        continue
                    wh_id = item.warehouse_id or inv.warehouse_id
                    if not wh_id:
                        default_wh = default_wh or await self._default_warehouse_id(company_id)
                        wh_id = default_wh
                    if not wh_id:
                        continue
                    is_return = inv.invoice_type == "credit_note"
                await inv_svc.record_movement(
                    company_id=company_id, product_id=item.product_id, warehouse_id=wh_id,
                    movement_type="sale_reversal",
                    quantity=-item.quantity if is_return else item.quantity,
                    ref_type="invoice", ref_id=inv.id, ref_no=inv.invoice_no,
                    narration=f"{'Credit note' if is_return else 'Invoice'} {inv.invoice_no} cancelled",
                    user_id=user_id,
                )
            except Exception as e:
                import traceback
                print("STOCK REVERSAL ON CANCEL FAILED:", e)
                traceback.print_exc()

            # NEW — also reverse the associated journal voucher, not just stock
            try:
                from app.db.models.accounting import JournalVoucher
                from app.services.accounting import JournalVoucherService
                jv_result = await self.session.execute(
                    select(JournalVoucher).where(
                        JournalVoucher.company_id == company_id,
                        JournalVoucher.ref_type == "invoice",
                        JournalVoucher.ref_id == inv.id,
                        JournalVoucher.is_reversed == False,
                    )
                )
                jv = jv_result.scalars().first()
                if jv and jv.is_posted:
                    jv_svc = JournalVoucherService(self.session)
                    await jv_svc.reverse(jv.id, company_id, user_id)
            except Exception as e:
                import traceback
                print("JV REVERSAL ON CANCEL FAILED:", e)
                traceback.print_exc()
        return await self.repo.update(inv, {
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc),
            "cancelled_by": user_id,
            "cancel_reason": reason,
        })

    async def record_payment(self, invoice_id: UUID, amount: Decimal, company_id: UUID) -> Invoice:
        inv = await self.repo.get_or_raise_scoped(invoice_id, company_id=company_id)
        new_paid = inv.paid_amount + amount
        new_status = "paid" if new_paid >= inv.total_amount else "partial"
        return await self.repo.update(inv, {"paid_amount": new_paid, "status": new_status})

    async def get_pdf_data(self, invoice_id: UUID, company_id: UUID) -> bytes:
        from app.utils.pdf_generator import PDFDocumentData, generate_invoice_pdf
        inv = await self.repo.get_detail(invoice_id)
        if not inv:
            raise NotFoundError("Invoice not found.")
        from app.db.repositories import CompanyRepository, UnitOfMeasureRepository, ProductRepository
        company_repo = CompanyRepository(self.session)
        company = await company_repo.get(company_id)

        uom_repo = UnitOfMeasureRepository(self.session)
        product_repo = ProductRepository(self.session)
        product_uom_cache: dict = {}
        resolved_uom_ids = []
        for it in inv.items:
            uid = it.uom_id
            if not uid and it.product_id:
                if it.product_id not in product_uom_cache:
                    prod = await product_repo.get(it.product_id)
                    product_uom_cache[it.product_id] = prod.uom_id if prod else None
                uid = product_uom_cache[it.product_id]
            resolved_uom_ids.append(uid)
        uom_names = {}
        for uid in set(u for u in resolved_uom_ids if u):
            uom = await uom_repo.get(uid)
            if uom:
                uom_names[uid] = uom.uom_code or uom.uom_name

        items_data = [
            {
                "line_no": i + 1,
                "description": it.description,
                "hsn_code": it.hsn_code or "",
                "unit": uom_names.get(resolved_uom_ids[i], ""),
                "quantity": str(it.quantity),
                "rate": it.rate,
                "discount_amount": it.discount_amount,
                "taxable_amount": it.taxable_amount,
                "gst_rate": it.gst_rate,
                "cgst_amount": it.cgst_amount,
                "sgst_amount": it.sgst_amount,
                "igst_amount": it.igst_amount,
                "total_amount": it.total_amount,
            }
            for i, it in enumerate(inv.items)
        ]
        against_invoice_no = None
        against_invoice_date = None
        if inv.against_invoice_id:
            ref_inv = await self.repo.get(inv.against_invoice_id)
            if ref_inv:
                against_invoice_no = ref_inv.invoice_no
                against_invoice_date = ref_inv.invoice_date

        data = PDFDocumentData(
            doc_type=inv.invoice_type if inv.invoice_type in ("credit_note", "debit_note") else "invoice",
            doc_no=inv.invoice_no,
            doc_date=inv.invoice_date,
            due_date=inv.due_date,
            against_invoice_no=against_invoice_no,
            against_invoice_date=against_invoice_date,
            company_name=company.legal_name if company else "",
            company_tagline=((company.settings or {}).get("tagline", "") if company else ""),
            company_gstin=company.gstin or "" if company else "",
            company_address=company.reg_address or "" if company else "",
            company_phone=company.phone or "" if company else "",
            company_email=company.email or "" if company else "",
            company_logo_url=(company.logo_url or "") if company else "",
            party_name=inv.billing_name,
            party_gstin=inv.billing_gstin or "",
            party_address=inv.billing_address or "",
            party_phone=inv.contact_phone or "",
            po_no=inv.po_no,
            po_date=inv.po_date,
            status=inv.status,
            jo_no=inv.jo_no,
            company_pan=company.pan if company else "",
            eway_bill_no=inv.ewb_no or "",
            transporter_name=inv.transporter_name or "",
            transporter_id=inv.transporter_id or "",
            vehicle_no=inv.vehicle_no or "",
            upi_id=(company.settings or {}).get("upi_id", "") if company else "",
            bank_name=(company.settings or {}).get("bank_name", "") if company else "",
            bank_branch=(company.settings or {}).get("bank_branch", "") if company else "",
            bank_account_no=(company.settings or {}).get("bank_account_no", "") if company else "",
            bank_ifsc=(company.settings or {}).get("bank_ifsc", "") if company else "",
            terms_conditions=inv.terms_conditions or ((company.settings or {}).get("default_terms", "") if company else ""),
            page_size=(company.settings or {}).get("pdf_page_size", "A4") if company else "A4",
            show_upi_qr=(company.settings or {}).get("show_upi_qr", True) if company else True,
            signature_url=(company.settings or {}).get("signature_url") if company else None,
            copy_label=(company.settings or {}).get("default_copy_label", "ORIGINAL FOR RECIPIENT") if company else "ORIGINAL FOR RECIPIENT",
            place_of_supply=inv.place_of_supply,
            supply_type=inv.supply_type,
            items=items_data,
            subtotal=inv.subtotal,
            discount_amount=inv.discount_amount,
            taxable_amount=inv.taxable_amount,
            cgst_amount=inv.cgst_amount,
            sgst_amount=inv.sgst_amount,
            igst_amount=inv.igst_amount,
            cess_amount=inv.cess_amount,
            other_charges=inv.other_charges,
            tds_amount=inv.tds_amount,
            round_off=inv.round_off,
            total_amount=inv.total_amount,
            irn=inv.irn,
            ack_no=inv.ack_no,
            notes=inv.notes or "",
        )
        return generate_invoice_pdf(data)

    async def preview_pdf(self, company_id: UUID, payload: InvoiceCreate) -> bytes:
        """Generate the real invoice PDF straight from an unsaved payload.
        No sequence number is consumed, nothing is written to the DB — this
        exists purely so 'Preview' can show the actual rendered document
        before the user commits to saving anything."""
        from app.utils.pdf_generator import PDFDocumentData, generate_invoice_pdf
        from app.db.repositories import CompanyRepository, UnitOfMeasureRepository, ProductRepository

        lines, totals = _calc_items(payload.items, payload.supply_type)

        company_repo = CompanyRepository(self.session)
        company = await company_repo.get(company_id)

        uom_repo = UnitOfMeasureRepository(self.session)
        product_repo = ProductRepository(self.session)
        product_uom_cache: dict = {}
        resolved_uom_ids = []
        for item in payload.items:
            uid = item.uom_id
            if not uid and item.product_id:
                if item.product_id not in product_uom_cache:
                    prod = await product_repo.get(item.product_id)
                    product_uom_cache[item.product_id] = prod.uom_id if prod else None
                uid = product_uom_cache[item.product_id]
            resolved_uom_ids.append(uid)
        uom_names = {}
        for uid in set(u for u in resolved_uom_ids if u):
            uom = await uom_repo.get(uid)
            if uom:
                uom_names[uid] = uom.uom_code or uom.uom_name

        items_data = [{
            "line_no": i + 1,
            "description": line.description,
            "hsn_code": line.hsn_code or "",
            "unit": uom_names.get(resolved_uom_ids[i], ""),
            "quantity": str(line.quantity),
            "rate": line.rate,
            "discount_amount": line.discount_amount,
            "taxable_amount": line.taxable_amount,
            "gst_rate": line.gst_rate,
            "cgst_amount": line.cgst_amount,
            "sgst_amount": line.sgst_amount,
            "igst_amount": line.igst_amount,
            "total_amount": line.total_amount,
        } for i, line in enumerate(lines)]

        from decimal import ROUND_HALF_UP
        raw_total = (totals["taxable_amount"] + totals["cgst_amount"] + totals["sgst_amount"]
                     + totals["igst_amount"] + totals["cess_amount"] + payload.other_charges)
        rounded = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        data = PDFDocumentData(
            doc_type=payload.invoice_type if payload.invoice_type in ("credit_note", "debit_note") else "invoice",
            doc_no="PREVIEW",
            doc_date=payload.invoice_date,
            due_date=payload.due_date,
            company_name=company.legal_name if company else "",
            company_tagline=((company.settings or {}).get("tagline", "") if company else ""),
            company_gstin=company.gstin or "" if company else "",
            company_address=company.reg_address or "" if company else "",
            company_phone=company.phone or "" if company else "",
            company_email=company.email or "" if company else "",
            company_logo_url=(company.logo_url or "") if company else "",
            company_pan=company.pan if company else "",
            party_name=payload.billing_name,
            party_gstin=payload.billing_gstin or "",
            party_address=payload.billing_address or "",
            party_phone=payload.contact_phone or "",
            status="draft",
            upi_id=(company.settings or {}).get("upi_id", "") if company else "",
            bank_name=(company.settings or {}).get("bank_name", "") if company else "",
            bank_branch=(company.settings or {}).get("bank_branch", "") if company else "",
            bank_account_no=(company.settings or {}).get("bank_account_no", "") if company else "",
            bank_ifsc=(company.settings or {}).get("bank_ifsc", "") if company else "",
            terms_conditions=payload.terms_conditions or ((company.settings or {}).get("default_terms", "") if company else ""),
            page_size=(company.settings or {}).get("pdf_page_size", "A4") if company else "A4",
            show_upi_qr=(company.settings or {}).get("show_upi_qr", True) if company else True,
            signature_url=(company.settings or {}).get("signature_url") if company else None,
            place_of_supply=payload.place_of_supply,
            supply_type=payload.supply_type,
            items=items_data,
            subtotal=totals["subtotal"],
            discount_amount=totals["discount_amount"],
            taxable_amount=totals["taxable_amount"],
            cgst_amount=totals["cgst_amount"],
            sgst_amount=totals["sgst_amount"],
            igst_amount=totals["igst_amount"],
            cess_amount=totals["cess_amount"],
            other_charges=payload.other_charges,
            round_off=rounded - raw_total,
            total_amount=rounded,
            notes=payload.notes or "",
            copy_label="PREVIEW \u2013 NOT A VALID TAX INVOICE",
        )
        return generate_invoice_pdf(data)
    
    async def update(self, invoice_id: UUID, company_id: UUID, payload: InvoiceUpdate, user_id: UUID) -> Invoice:
        result = await self.session.execute(
            select(Invoice).where(Invoice.id == invoice_id).options(selectinload(Invoice.items))
        )
        inv = result.scalar_one_or_none()
        if not inv:
            raise NotFoundError("Invoice not found.")
        if inv.company_id != company_id:
            from app.core.exceptions import PermissionDeniedError
            raise PermissionDeniedError()

        data = payload.model_dump(exclude_unset=True, exclude={"items"})

        if inv.status == "draft":
            # Draft invoices: everything the payload sent is fair game
            update_fields = data
            if payload.items is not None:
                lines, totals = _calc_items(payload.items, payload.supply_type or inv.supply_type)
                from decimal import ROUND_HALF_UP
                raw_total = (totals["taxable_amount"] + totals["cgst_amount"] + totals["sgst_amount"] +
                             totals["igst_amount"] + totals["cess_amount"] +
                             (payload.other_charges if payload.other_charges is not None else inv.other_charges) -
                             (payload.tds_amount if payload.tds_amount is not None else inv.tds_amount) +
                             (payload.tcs_amount if payload.tcs_amount is not None else inv.tcs_amount))
                rounded = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                round_off = rounded - raw_total + (payload.round_off if payload.round_off is not None else Decimal("0"))

                # Replace line items entirely
                for old_item in list(inv.items):
                    inv.items.remove(old_item)   # detach from the in-memory collection first
                    await self.session.delete(old_item)
                await self.session.flush()

                for line in lines:
                    item = payload.items[line.line_no - 1]
                    is_igst = (payload.supply_type or inv.supply_type) == "inter"
                    self.session.add(InvoiceItem(
                        invoice_id=inv.id,
                        product_id=item.product_id,
                        description=item.description,
                        hsn_code=item.hsn_code,
                        quantity=item.quantity,
                        rate=item.rate,
                        discount_pct=item.discount_pct,
                        gst_rate=item.gst_rate,
                        cgst_rate=Decimal("0") if is_igst else item.gst_rate / 2,
                        sgst_rate=Decimal("0") if is_igst else item.gst_rate / 2,
                        igst_rate=item.gst_rate if is_igst else Decimal("0"),
                        taxable_amount=line.taxable_amount,
                        cgst_amount=line.cgst_amount,
                        sgst_amount=line.sgst_amount,
                        igst_amount=line.igst_amount,
                        cess_amount=line.cess_amount,
                        total_amount=line.total_amount,
                    ))

                update_fields.update({
                    "round_off": round_off,
                    "total_amount": rounded,
                    **totals,
                })
        else:
            # Anything not a draft — keep today's narrow, safe whitelist
            allowed = {"due_date", "notes"}
            update_fields = {k: v for k, v in data.items() if k in allowed}

        return await self.repo.update(inv, update_fields)


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = PaymentRepository(session)
        self.inv_repo = InvoiceRepository(session)
        self.seq = DocumentSequenceRepository(session)
        self.session = session

    async def create(self, company_id: UUID, payload: PaymentCreate, user_id: UUID) -> Payment:
        pay_no = await self.seq.next_number(company_id, "payment")
        payment = await self.repo.create({
            "company_id": company_id,
            "payment_no": pay_no,
            "payment_type": payload.payment_type,
            "payment_date": payload.payment_date,
            "party_id": payload.party_id,
            "amount": payload.amount,
            "payment_method": payload.payment_method,
            "cheque_no": payload.cheque_no,
            "cheque_date": payload.cheque_date,
            "bank_ref_no": payload.bank_ref_no,
            "upi_ref_no": payload.upi_ref_no,
            "gateway_txn_id": payload.gateway_txn_id,
            "narration": payload.narration,
            "status": "completed",
            "created_by": user_id,
        })
        remaining = payload.amount
        for alloc in payload.allocations:
            if remaining <= 0:
                break
            inv_id = UUID(str(alloc["invoice_id"]))
            alloc_amt = min(Decimal(str(alloc["amount"])), remaining)
            self.session.add(PaymentAllocation(
                payment_id=payment.id,
                invoice_id=inv_id,
                ref_type="invoice",
                amount=alloc_amt,
            ))
            inv = await self.inv_repo.get(inv_id)
            if inv:
                new_paid = inv.paid_amount + alloc_amt
                new_status = "paid" if new_paid >= inv.total_amount else "partial"
                await self.inv_repo.update(inv, {"paid_amount": new_paid, "status": new_status})
            remaining -= alloc_amt
        await self.session.flush()

        # NEW — post to Ledger & Books, direction depends on payment_type
        if payload.party_id:
            from app.services.accounting import AutoAccountingService
            auto = AutoAccountingService(self.session)
            if payload.payment_type == "receipt":
                await auto.on_payment_received(
                    company_id=company_id, payment_id=payment.id, payment_no=pay_no,
                    payment_date=payload.payment_date, party_id=payload.party_id,
                    amount=payload.amount, payment_method=payload.payment_method, user_id=user_id,
                )
            elif payload.payment_type == "payment":
                await auto.on_payment_made(
                    company_id=company_id, payment_id=payment.id, payment_no=pay_no,
                    payment_date=payload.payment_date, party_id=payload.party_id,
                    amount=payload.amount, payment_method=payload.payment_method, user_id=user_id,
                )

        return payment
