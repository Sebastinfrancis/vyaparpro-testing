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
from app.db.sql_compat import month_start_sql


class DocumentSequenceRepository(BaseRepository[DocumentSequence]):
    model = DocumentSequence

    # Document types exposed in Settings → Document Numbering. (jo/grn/dc exist
    # in the DB too but aren't surfaced there since they aren't part of the
    # day-to-day billing flow.)
    DOC_TYPE_LABELS = {
        "invoice": "Invoices, Credit & Debit Notes",
        "quote": "Quotations",
        "po": "Purchase Orders",
        "payment": "Payment Vouchers",
    }

    @staticmethod
    def _current_fy() -> str:
        from datetime import date as dt
        today = dt.today()
        return f"{today.year}-{str(today.year+1)[2:]}" if today.month >= 4 else f"{today.year-1}-{str(today.year)[2:]}"

    async def list_for_company(self, company_id: UUID, branch_id: UUID | None = None) -> list[dict]:
        """One row per configurable doc type, scoped to a single branch (or the
        company-wide/head-office series when branch_id is None). Returns a live
        DB row if one exists for the current financial year, otherwise the same
        defaults next_number() would fall back to, so the settings screen
        always has something sane to show even before a branch has issued its
        first document."""
        fy = self._current_fy()
        stmt = select(DocumentSequence).where(
            DocumentSequence.company_id == company_id,
            DocumentSequence.doc_type.in_(list(self.DOC_TYPE_LABELS)),
            DocumentSequence.branch_id.is_(None) if branch_id is None else DocumentSequence.branch_id == branch_id,
        )
        rows = {
            r.doc_type: r for r in (await self.session.execute(stmt)).scalars().all()
            if r.financial_year == fy or not r.reset_on_fy
        }
        defaults = {"invoice": "INV-", "quote": "QT-", "po": "PO-", "payment": "PAY-"}
        out = []
        for doc_type, label in self.DOC_TYPE_LABELS.items():
            row = rows.get(doc_type)
            if row:
                out.append({
                    "doc_type": doc_type, "label": label, "branch_id": row.branch_id,
                    "prefix": row.prefix, "suffix": row.suffix, "next_number": row.current_no + 1,
                    "pad_length": row.pad_length, "reset_on_fy": row.reset_on_fy, "financial_year": row.financial_year,
                })
            else:
                out.append({
                    "doc_type": doc_type, "label": label, "branch_id": branch_id, "prefix": defaults[doc_type],
                    "suffix": None, "next_number": 1, "pad_length": 4, "reset_on_fy": True, "financial_year": fy,
                })
        return out

    async def upsert(self, company_id: UUID, doc_type: str, branch_id: UUID | None, data: dict) -> dict:
        """Creates or updates this year's row for one doc type, scoped to a
        single branch (or the head-office series when branch_id is None).
        `next_number` from the API is the number the *next* generated document
        should get, so it's stored internally as current_no = next_number - 1
        (next_number() does current_no + 1 when it actually issues a number)."""
        fy = self._current_fy()
        stmt = select(DocumentSequence).where(
            DocumentSequence.company_id == company_id,
            DocumentSequence.doc_type == doc_type,
            DocumentSequence.branch_id.is_(None) if branch_id is None else DocumentSequence.branch_id == branch_id,
        )
        row = (await self.session.execute(stmt)).scalars().first()
        values = {
            "prefix": data["prefix"], "suffix": data.get("suffix"),
            "current_no": max(data["next_number"] - 1, 0), "pad_length": data["pad_length"],
            "reset_on_fy": data["reset_on_fy"], "financial_year": fy,
        }
        if row:
            row = await self.update(row, values)
        else:
            row = await self.create({"company_id": company_id, "branch_id": branch_id, "doc_type": doc_type, **values})
        return {
            "doc_type": row.doc_type, "label": self.DOC_TYPE_LABELS.get(row.doc_type, row.doc_type),
            "branch_id": row.branch_id, "prefix": row.prefix, "suffix": row.suffix,
            "next_number": row.current_no + 1, "pad_length": row.pad_length,
            "reset_on_fy": row.reset_on_fy, "financial_year": row.financial_year,
        }

    async def next_number(self, company_id: UUID, doc_type: str, branch_id: UUID | None = None,
                          branch_code: str | None = None) -> str:
        from sqlalchemy import text as t_
        fy = self._current_fy()
        # IMPORTANT: match branch_id exactly, including NULL — "IS NOT DISTINCT FROM"
        # is Postgres's null-safe equality. Without this, every branch would
        # collide onto the same counter the moment one existed for that doc_type.
        stmt = t_("""
            UPDATE document_sequences
            SET current_no = current_no + 1, last_used_at = CURRENT_TIMESTAMP
            WHERE company_id=:cid AND doc_type=:dt AND branch_id IS NOT DISTINCT FROM :bid
              AND (financial_year=:fy OR reset_on_fy=FALSE)
            RETURNING prefix, current_no, pad_length, suffix
        """)
        result = await self.session.execute(
            stmt, {"cid": str(company_id), "dt": doc_type, "bid": str(branch_id) if branch_id else None, "fy": fy}
        )
        row = result.mappings().one_or_none()
        if not row:
            # No row for this branch + doc type this FY (first document ever
            # for this branch, or a fresh year rolled over on a
            # reset_on_fy=True series). Inherit prefix/suffix/padding/reset-rule
            # from this same branch's most recent prior row — e.g. what was
            # configured in Settings → Document Numbering — so a custom
            # numbering format (including a branch-code prefix) survives the
            # financial-year rollover instead of reverting to the generic
            # default below.
            prior_stmt = (
                select(DocumentSequence)
                .where(
                    DocumentSequence.company_id == company_id,
                    DocumentSequence.doc_type == doc_type,
                    DocumentSequence.branch_id.is_(None) if branch_id is None else DocumentSequence.branch_id == branch_id,
                )
                .order_by(DocumentSequence.financial_year.desc().nullslast(), DocumentSequence.created_at.desc())
                .limit(1)
            )
            prior = (await self.session.execute(prior_stmt)).scalars().first()
            if prior:
                prefix, suffix, pad_length, reset_on_fy = prior.prefix, prior.suffix, prior.pad_length, prior.reset_on_fy
            else:
                prefix_map = {"invoice":"INV","po":"PO","jo":"JO","quote":"QT","grn":"GRN","dc":"DC","payment":"PAY","adjustment":"ADJ","transfer":"TRF"}
                doc_prefix = prefix_map.get(doc_type, doc_type.upper()[:3])
                # Branch-code prefix (e.g. "ANA-INV-0001") lets each location's
                # documents be told apart at a glance — standard practice once a
                # business has more than one GST registration issuing the same
                # document type in parallel.
                prefix = f"{branch_code}-{doc_prefix}-" if branch_code else f"{doc_prefix}-"
                suffix, pad_length, reset_on_fy = None, 4, True
            seq = await self.create({"company_id": company_id, "branch_id": branch_id, "doc_type": doc_type,
                                     "prefix": prefix, "suffix": suffix, "current_no": 1, "pad_length": pad_length,
                                     "financial_year": fy, "reset_on_fy": reset_on_fy})
            return f"{seq.prefix}{str(1).zfill(seq.pad_length)}{seq.suffix or ''}"
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
        stmt = text(f"""
            SELECT
                COUNT(*) FILTER (WHERE status NOT IN ('cancelled','void','draft')) AS total_invoices,
                COALESCE(SUM(total_amount) FILTER (WHERE status NOT IN ('cancelled','void','draft')), 0) AS total_value,
                COALESCE(SUM(total_amount - paid_amount) FILTER (WHERE status NOT IN ('paid','cancelled','void','draft')), 0) AS outstanding,
                COUNT(*) FILTER (WHERE due_date < CURRENT_DATE AND status NOT IN ('paid','cancelled','void','draft')) AS overdue_count,
                COALESCE(SUM(total_amount) FILTER (WHERE invoice_date >= {month_start_sql()}), 0) AS mtd_sales
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
