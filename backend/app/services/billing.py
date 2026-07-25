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
from app.utils.gst_calculator import GSTCalculator
from sqlalchemy import select
from sqlalchemy.orm import selectinload


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

    async def create(self, company_id: UUID, payload: PurchaseOrderCreate, user_id: UUID) -> PurchaseOrder:
        lines, totals = _calc_items(payload.items, "intra")
        total = totals["taxable_amount"] + totals["cgst_amount"] + totals["sgst_amount"] + totals["igst_amount"] + totals["cess_amount"] + payload.other_charges
        po_no = await self.seq.next_number(company_id, "po")
        po = await self.repo.create({
            "company_id": company_id,
            "po_no": po_no,
            "po_date": payload.po_date,
            "vendor_id": payload.vendor_id,
            "vendor_ref_no": payload.vendor_ref_no,
            "linked_jo_id": payload.linked_jo_id,
            "deliver_to_warehouse_id": payload.deliver_to_warehouse_id,
            "expected_delivery": payload.expected_delivery,
            "currency": payload.currency,
            "payment_terms": payload.payment_terms,
            "delivery_terms": payload.delivery_terms,
            "special_instructions": payload.special_instructions,
            "notes": payload.notes,
            "other_charges": payload.other_charges,
            "created_by": user_id,
            "status": "open",
            "approval_status": "pending",
            **totals,
            "total_amount": total,
        })
        for line in lines:
            item = payload.items[line.line_no - 1]
            self.session.add(PurchaseOrderItem(
                po_id=po.id,
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
                amount=line.total_amount,
                total_amount=line.total_amount,
                display_order=item.display_order,
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
            )

        all_received = all(it.received_qty >= it.quantity for it in po.items if it.product_id)
        await self.repo.update(po, {
            "status": "received" if all_received else "partially_received",
            "actual_delivery": date.today(),
        })
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
        lines, totals = _calc_items(payload.items, payload.supply_type)
        from decimal import ROUND_HALF_UP
        raw_total = (totals["taxable_amount"] + totals["cgst_amount"] + totals["sgst_amount"] +
                     totals["igst_amount"] + totals["cess_amount"] + payload.other_charges -
                     payload.tds_amount + payload.tcs_amount)
        rounded = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        round_off = rounded - raw_total + payload.round_off
        inv_no = await self.seq.next_number(company_id, "invoice")
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
            "quote_id": payload.quote_id,
            "dc_id": payload.dc_id,
            "against_invoice_id": payload.against_invoice_id,
            "place_of_supply": payload.place_of_supply,
            "supply_type": payload.supply_type,
            "reverse_charge": payload.reverse_charge,
            "currency": payload.currency,
            "warehouse_id": payload.warehouse_id,
            "payment_terms": payload.payment_terms,
            "notes": payload.notes,
            "terms_conditions": payload.terms_conditions,
            "other_charges": payload.other_charges,
            "tds_amount": payload.tds_amount,
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
        inv = await self.repo.get_or_raise(invoice_id)
        if inv.company_id != company_id:
            from app.core.exceptions import PermissionDeniedError
            raise PermissionDeniedError()
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
                await inv_svc.record_movement(
                    company_id=company_id, product_id=item.product_id, warehouse_id=wh_id,
                    movement_type="sale", quantity=-item.quantity,
                    ref_type="invoice", ref_id=inv.id, ref_no=inv.invoice_no,
                    narration=f"Sale via invoice {inv.invoice_no}", user_id=user_id,
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
            )
        except Exception:
            pass  # Accounting optional at this stage
        return updated

    async def cancel(self, invoice_id: UUID, company_id: UUID, reason: str, user_id: UUID) -> Invoice:
        inv = await self.repo.get_or_raise(invoice_id)
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
                    await inv_svc.record_movement(
                        company_id=company_id, product_id=item.product_id, warehouse_id=wh_id,
                        movement_type="sale_reversal", quantity=item.quantity,
                        ref_type="invoice", ref_id=inv.id, ref_no=inv.invoice_no,
                        narration=f"Invoice {inv.invoice_no} cancelled", user_id=user_id,
                    )
            except Exception:
                pass
        return await self.repo.update(inv, {
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc),
            "cancelled_by": user_id,
            "cancel_reason": reason,
        })

    async def record_payment(self, invoice_id: UUID, amount: Decimal, company_id: UUID) -> Invoice:
        inv = await self.repo.get_or_raise(invoice_id)
        new_paid = inv.paid_amount + amount
        new_status = "paid" if new_paid >= inv.total_amount else "partial"
        return await self.repo.update(inv, {"paid_amount": new_paid, "status": new_status})

    async def get_pdf_data(self, invoice_id: UUID, company_id: UUID) -> bytes:
        from app.utils.pdf_generator import PDFDocumentData, generate_invoice_pdf
        inv = await self.repo.get_detail(invoice_id)
        if not inv:
            raise NotFoundError("Invoice not found.")
        from app.db.repositories import CompanyRepository
        company_repo = CompanyRepository(self.session)
        company = await company_repo.get(company_id)
        items_data = [
            {
                "line_no": i + 1,
                "description": it.description,
                "hsn_code": it.hsn_code or "",
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
        data = PDFDocumentData(
            doc_type="invoice",
            doc_no=inv.invoice_no,
            doc_date=inv.invoice_date,
            due_date=inv.due_date,
            company_name=company.legal_name if company else "",
            company_gstin=company.gstin or "" if company else "",
            company_address=company.reg_address or "" if company else "",
            company_phone=company.phone or "" if company else "",
            company_email=company.email or "" if company else "",
            party_name=inv.billing_name,
            party_gstin=inv.billing_gstin or "",
            party_address=inv.billing_address or "",
            po_no=inv.po_no,
            po_date=inv.po_date,
            jo_no=inv.jo_no,
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
        return payment
