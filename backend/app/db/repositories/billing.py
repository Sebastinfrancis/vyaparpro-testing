"""VyaparPro – Billing Repositories"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import selectinload
from app.db.models.billing import (
    DeliveryChallan, DeliveryChallanItem, DocumentSequence,
    EInvoiceLog, GoodsReceiptNote, GRNItem, Invoice, InvoiceItem,
    JobOrder, JobOrderItem, Payment, PaymentAllocation,
    PurchaseOrder, PurchaseOrderItem, Quotation, QuotationItem,
)
from app.db.repositories.base import BaseRepository, Pagination


class DocumentSequenceRepository(BaseRepository[DocumentSequence]):
    model = DocumentSequence

    async def next_number(self, company_id: UUID, doc_type: str, branch_id: UUID | None = None) -> str:
        from datetime import date as dt
        from sqlalchemy import text as t_
        today = dt.today()
        fy = f"{today.year}-{str(today.year+1)[2:]}" if today.month >= 4 else f"{today.year-1}-{str(today.year)[2:]}"
        stmt = t_("""
            UPDATE document_sequences
            SET current_no = current_no + 1, last_used_at = NOW()
            WHERE company_id=:cid AND doc_type=:dt AND (financial_year=:fy OR reset_on_fy=FALSE)
            RETURNING prefix, current_no, pad_length, suffix
        """)
        result = await self.session.execute(stmt, {"cid": str(company_id), "dt": doc_type, "fy": fy})
        row = result.mappings().one_or_none()
        if not row:
            prefix_map = {"invoice":"INV","po":"PO","jo":"JO","quote":"QT","grn":"GRN","dc":"DC","payment":"PAY","adjustment":"ADJ","transfer":"TRF"}
            prefix = prefix_map.get(doc_type, doc_type.upper()[:3])
            seq = await self.create({"company_id": company_id, "branch_id": branch_id, "doc_type": doc_type,
                                     "prefix": f"{prefix}-", "current_no": 1, "pad_length": 4,
                                     "financial_year": fy, "reset_on_fy": True})
            return f"{seq.prefix}{str(1).zfill(seq.pad_length)}"
        return f"{row['prefix']}{str(row['current_no']).zfill(row['pad_length'])}{row['suffix'] or ''}"


class QuotationRepository(BaseRepository[Quotation]):
    model = Quotation

    async def search(self, company_id: UUID, query: str | None = None, status: str | None = None,
                     from_date: date | None = None, to_date: date | None = None,
                     page: int = 1, page_size: int = 20) -> Pagination:
        stmt = (select(Quotation).where(Quotation.company_id == company_id)
                .options(selectinload(Quotation.items)))
        if query:
            stmt = stmt.where(or_(Quotation.quote_no.ilike(f"%{query}%"),
                                  Quotation.billing_name.ilike(f"%{query}%")))
        if status:
            stmt = stmt.where(Quotation.status == status)
        if from_date:
            stmt = stmt.where(Quotation.quote_date >= from_date)
        if to_date:
            stmt = stmt.where(Quotation.quote_date <= to_date)
        stmt = stmt.order_by(Quotation.quote_date.desc())
        return await self.paginate(stmt, page, page_size)

    async def get_detail(self, quote_id: UUID) -> Quotation | None:
        stmt = (select(Quotation).where(Quotation.id == quote_id)
                .options(selectinload(Quotation.items), selectinload(Quotation.party)))
        return (await self.session.execute(stmt)).scalar_one_or_none()


class JobOrderRepository(BaseRepository[JobOrder]):
    model = JobOrder

    async def search(self, company_id: UUID, query: str | None = None, status: str | None = None,
                     from_date: date | None = None, to_date: date | None = None,
                     page: int = 1, page_size: int = 20) -> Pagination:
        stmt = (select(JobOrder).where(JobOrder.company_id == company_id)
                .options(selectinload(JobOrder.items)))
        if query:
            stmt = stmt.where(or_(JobOrder.jo_no.ilike(f"%{query}%"),
                                  JobOrder.billing_name.ilike(f"%{query}%"),
                                  JobOrder.title.ilike(f"%{query}%")))
        if status:
            stmt = stmt.where(JobOrder.status == status)
        if from_date:
            stmt = stmt.where(JobOrder.jo_date >= from_date)
        if to_date:
            stmt = stmt.where(JobOrder.jo_date <= to_date)
        stmt = stmt.order_by(JobOrder.jo_date.desc())
        return await self.paginate(stmt, page, page_size)

    async def get_detail(self, jo_id: UUID) -> JobOrder | None:
        stmt = (select(JobOrder).where(JobOrder.id == jo_id)
                .options(selectinload(JobOrder.items), selectinload(JobOrder.party)))
        return (await self.session.execute(stmt)).scalar_one_or_none()


class PurchaseOrderRepository(BaseRepository[PurchaseOrder]):
    model = PurchaseOrder

    async def search(self, company_id: UUID, query: str | None = None, status: str | None = None,
                     vendor_id: UUID | None = None, from_date: date | None = None,
                     to_date: date | None = None, page: int = 1, page_size: int = 20) -> Pagination:
        stmt = (select(PurchaseOrder).where(PurchaseOrder.company_id == company_id)
                .options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.vendor)))
        if query:
            stmt = stmt.where(or_(PurchaseOrder.po_no.ilike(f"%{query}%")))
        if status:
            stmt = stmt.where(PurchaseOrder.status == status)
        if vendor_id:
            stmt = stmt.where(PurchaseOrder.vendor_id == vendor_id)
        if from_date:
            stmt = stmt.where(PurchaseOrder.po_date >= from_date)
        if to_date:
            stmt = stmt.where(PurchaseOrder.po_date <= to_date)
        stmt = stmt.order_by(PurchaseOrder.po_date.desc())
        return await self.paginate(stmt, page, page_size)

    async def sum_taxable_for_vendor_in_fy(
        self, company_id: UUID, vendor_id: UUID, fy_start: date, fy_end: date
    ) -> Decimal:
        """Total taxable value already purchased from this vendor in the given financial year
        (excludes cancelled POs — used to test TDS threshold crossing)."""
        stmt = select(func.coalesce(func.sum(PurchaseOrder.taxable_amount), Decimal("0"))).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.vendor_id == vendor_id,
            PurchaseOrder.status != "cancelled",
            PurchaseOrder.po_date >= fy_start,
            PurchaseOrder.po_date <= fy_end,
        )
        result = await self.session.execute(stmt)
        return result.scalar() or Decimal("0")

    async def get_detail(self, po_id: UUID) -> PurchaseOrder | None:
        stmt = (select(PurchaseOrder).where(PurchaseOrder.id == po_id)
                .options(selectinload(PurchaseOrder.items),
                         selectinload(PurchaseOrder.vendor),
                         selectinload(PurchaseOrder.job_order),
                         selectinload(PurchaseOrder.grns)))
        return (await self.session.execute(stmt)).scalar_one_or_none()


class GoodsReceiptNoteRepository(BaseRepository[GoodsReceiptNote]):
    model = GoodsReceiptNote

    async def get_detail(self, grn_id: UUID) -> GoodsReceiptNote | None:
        stmt = (select(GoodsReceiptNote).where(GoodsReceiptNote.id == grn_id)
                .options(selectinload(GoodsReceiptNote.items), selectinload(GoodsReceiptNote.po)))
        return (await self.session.execute(stmt)).scalar_one_or_none()


class DeliveryChallanRepository(BaseRepository[DeliveryChallan]):
    model = DeliveryChallan

    async def search(self, company_id: UUID, query: str | None = None, page: int = 1, page_size: int = 20) -> Pagination:
        stmt = select(DeliveryChallan).where(DeliveryChallan.company_id == company_id)
        if query:
            stmt = stmt.where(or_(DeliveryChallan.dc_no.ilike(f"%{query}%"),
                                  DeliveryChallan.billing_name.ilike(f"%{query}%")))
        stmt = stmt.order_by(DeliveryChallan.dc_date.desc())
        return await self.paginate(stmt, page, page_size)


class InvoiceRepository(BaseRepository[Invoice]):
    model = Invoice

    async def sum_taxable_for_customer_in_fy(
        self, company_id: UUID, party_id: UUID, fy_start: date, fy_end: date
    ) -> Decimal:
        """Total taxable value already invoiced to this customer in the given financial year
        (excludes cancelled invoices — used to test TDS threshold crossing on the sales side)."""
        stmt = select(func.coalesce(func.sum(Invoice.taxable_amount), Decimal("0"))).where(
            Invoice.company_id == company_id,
            Invoice.party_id == party_id,
            Invoice.status != "cancelled",
            Invoice.invoice_type == "tax_invoice",
            Invoice.invoice_date >= fy_start,
            Invoice.invoice_date <= fy_end,
        )
        result = await self.session.execute(stmt)
        return result.scalar() or Decimal("0")

    async def search(self, company_id: UUID, query: str | None = None, status: str | None = None,
                     invoice_type: str | None = None, party_id: UUID | None = None,
                     from_date: date | None = None, to_date: date | None = None,
                     overdue_only: bool = False, page: int = 1, page_size: int = 20) -> Pagination:
        stmt = (select(Invoice).where(Invoice.company_id == company_id)
                .options(selectinload(Invoice.party), selectinload(Invoice.items)))
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(Invoice.invoice_no.ilike(like),
                                  Invoice.billing_name.ilike(like),
                                  Invoice.billing_gstin.ilike(like),
                                  Invoice.jo_no.ilike(like),
                                  Invoice.po_no.ilike(like)))
        if status:
            stmt = stmt.where(Invoice.status == status)
        if invoice_type:
            stmt = stmt.where(Invoice.invoice_type == invoice_type)
        if party_id:
            stmt = stmt.where(Invoice.party_id == party_id)
        if from_date:
            stmt = stmt.where(Invoice.invoice_date >= from_date)
        if to_date:
            stmt = stmt.where(Invoice.invoice_date <= to_date)
        if overdue_only:
            stmt = stmt.where(Invoice.due_date < date.today(),
                              Invoice.status.notin_(["paid", "cancelled", "void"]))
        stmt = stmt.order_by(Invoice.invoice_date.desc())
        return await self.paginate(stmt, page, page_size)

    async def get_detail(self, invoice_id: UUID) -> Invoice | None:
        stmt = (select(Invoice).where(Invoice.id == invoice_id)
                .options(selectinload(Invoice.items).selectinload(InvoiceItem.product if hasattr(InvoiceItem, 'product') else InvoiceItem.invoice),
                         selectinload(Invoice.party),
                         selectinload(Invoice.job_order),
                         selectinload(Invoice.purchase_order),
                         selectinload(Invoice.payments)))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_no(self, company_id: UUID, invoice_no: str) -> Invoice | None:
        return await self.get_by(company_id=company_id, invoice_no=invoice_no)

    async def get_outstanding(self, company_id: UUID, party_id: UUID | None = None) -> list[Invoice]:
        stmt = (select(Invoice).where(Invoice.company_id == company_id,
                                      Invoice.status.notin_(["paid", "cancelled", "void", "draft"]),
                                      Invoice.paid_amount < Invoice.total_amount))
        if party_id:
            stmt = stmt.where(Invoice.party_id == party_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_dashboard_stats(self, company_id: UUID) -> dict:
        stmt = text("""
            SELECT
                COUNT(*) FILTER (WHERE status NOT IN ('cancelled','void','draft')) AS total_invoices,
                COALESCE(SUM(total_amount) FILTER (WHERE status NOT IN ('cancelled','void','draft')), 0) AS total_value,
                COALESCE(SUM(total_amount - paid_amount) FILTER (WHERE status NOT IN ('paid','cancelled','void','draft')), 0) AS outstanding,
                COUNT(*) FILTER (WHERE due_date < CURRENT_DATE AND status NOT IN ('paid','cancelled','void','draft')) AS overdue_count,
                COALESCE(SUM(total_amount) FILTER (WHERE invoice_date >= date_trunc('month', CURRENT_DATE)), 0) AS mtd_sales
            FROM invoices WHERE company_id = :cid
        """)
        row = (await self.session.execute(stmt, {"cid": str(company_id)})).mappings().one()
        return dict(row)


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    async def search(self, company_id: UUID, payment_type: str | None = None,
                     party_id: UUID | None = None, from_date: date | None = None,
                     to_date: date | None = None, page: int = 1, page_size: int = 20) -> Pagination:
        stmt = (select(Payment).where(Payment.company_id == company_id)
                .options(selectinload(Payment.allocations)))
        if payment_type:
            stmt = stmt.where(Payment.payment_type == payment_type)
        if party_id:
            stmt = stmt.where(Payment.party_id == party_id)
        if from_date:
            stmt = stmt.where(Payment.payment_date >= from_date)
        if to_date:
            stmt = stmt.where(Payment.payment_date <= to_date)
        stmt = stmt.order_by(Payment.payment_date.desc())
        return await self.paginate(stmt, page, page_size)
