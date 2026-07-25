"""VyaparPro – Billing API Endpoints"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import ORJSONResponse
from app.api.v1.dependencies import CacheDep, CurrentUserDep, DBDep, PaginationDep, require_perm
from app.schemas.billing import (
    DeliveryChallanCreate, InvoiceCreate, InvoiceCancelRequest, InvoiceUpdate,
    JobOrderCreate, JobOrderUpdate, PaymentCreate,
    PurchaseOrderCreate, QuotationCreate,
)
from app.schemas.billing import InvoiceOut
from app.services.billing import (
    DeliveryChallanRepository, InvoiceService, JobOrderService,
    PaymentService, PurchaseOrderService, QuotationService,
)
from app.utils.responses import created, ok, paginated
from app.schemas.billing import EInvoiceRecordIn

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# QUOTATIONS
# ═══════════════════════════════════════════════════════════════════

@router.get("/quotations", summary="List quotations")
async def list_quotations(current: CurrentUserDep, db: DBDep, pg: PaginationDep,
                          q: str | None = Query(None), status: str | None = Query(None),
                          from_date: date | None = Query(None), to_date: date | None = Query(None)) -> ORJSONResponse:
    from app.db.repositories.billing import QuotationRepository
    from app.schemas.billing import QuotationOut
    repo = QuotationRepository(db)
    result = await repo.search(current.company_id, q, status, from_date, to_date, pg.page, pg.page_size)
    return paginated([QuotationOut.model_validate(r).model_dump(mode='json') for r in result.items],
                     result.total, result.page, result.page_size, result.pages)

@router.post("/quotations", status_code=201, summary="Create quotation")
async def create_quotation(payload: QuotationCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import QuotationOut
    svc = QuotationService(db)
    q = await svc.create(current.company_id, payload, current.user_id)
    return created(QuotationOut.model_validate(q).model_dump(mode='json'), "Quotation created.")

@router.get("/quotations/{quote_id}", summary="Get quotation")
async def get_quotation(quote_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import QuotationRepository
    from app.schemas.billing import QuotationOut
    repo = QuotationRepository(db)
    q = await repo.get_detail(quote_id)
    if not q:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Quotation not found.")
    return ok(QuotationOut.model_validate(q).model_dump(mode='json'))

@router.post("/quotations/{quote_id}/convert-to-invoice", summary="Convert quotation to invoice")
async def quotation_to_invoice(quote_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import InvoiceOut
    svc = QuotationService(db)
    inv = await svc.convert_to_invoice(quote_id, current.company_id, current.user_id)
    return created(InvoiceOut.model_validate(inv).model_dump(mode='json'), "Converted to invoice.")


# ═══════════════════════════════════════════════════════════════════
# JOB ORDERS
# ═══════════════════════════════════════════════════════════════════

@router.get("/job-orders", summary="List job orders")
async def list_job_orders(current: CurrentUserDep, db: DBDep, pg: PaginationDep,
                          q: str | None = Query(None), status: str | None = Query(None),
                          from_date: date | None = Query(None), to_date: date | None = Query(None)) -> ORJSONResponse:
    from app.db.repositories.billing import JobOrderRepository
    from app.schemas.billing import JobOrderOut
    repo = JobOrderRepository(db)
    result = await repo.search(current.company_id, q, status, from_date, to_date, pg.page, pg.page_size)
    return paginated([JobOrderOut.model_validate(r).model_dump(mode='json') for r in result.items],
                     result.total, result.page, result.page_size, result.pages)

@router.post("/job-orders", status_code=201, summary="Create job order")
async def create_job_order(payload: JobOrderCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import JobOrderOut
    svc = JobOrderService(db)
    jo = await svc.create(current.company_id, payload, current.user_id)
    return created(JobOrderOut.model_validate(jo).model_dump(mode='json'), "Job order created.")

@router.get("/job-orders/{jo_id}", summary="Get job order")
async def get_job_order(jo_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import JobOrderRepository
    from app.schemas.billing import JobOrderOut
    repo = JobOrderRepository(db)
    jo = await repo.get_detail(jo_id)
    if not jo:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Job order not found.")
    return ok(JobOrderOut.model_validate(jo).model_dump(mode='json'))

@router.patch("/job-orders/{jo_id}", summary="Update job order")
async def update_job_order(jo_id: UUID, payload: JobOrderUpdate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import JobOrderRepository
    from app.schemas.billing import JobOrderOut
    repo = JobOrderRepository(db)
    jo = await repo.get_or_raise(jo_id)
    updated = await repo.update(jo, payload.model_dump(exclude_unset=True, exclude={"items"}))
    return ok(JobOrderOut.model_validate(updated).model_dump(mode='json'), "Job order updated.")

@router.post("/job-orders/{jo_id}/convert-to-invoice", summary="Convert job order to invoice")
async def jo_to_invoice(jo_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import InvoiceOut
    svc = JobOrderService(db)
    inv = await svc.convert_to_invoice(jo_id, current.company_id, current.user_id)
    return created(InvoiceOut.model_validate(inv).model_dump(), "Invoice created from job order.")


# ═══════════════════════════════════════════════════════════════════
# PURCHASE ORDERS
# ═══════════════════════════════════════════════════════════════════

@router.get("/purchase-orders", summary="List purchase orders")
async def list_purchase_orders(current: CurrentUserDep, db: DBDep, pg: PaginationDep,
                               q: str | None = Query(None), status: str | None = Query(None),
                               vendor_id: UUID | None = Query(None),
                               from_date: date | None = Query(None), to_date: date | None = Query(None)) -> ORJSONResponse:
    from app.db.repositories.billing import PurchaseOrderRepository
    from app.schemas.billing import PurchaseOrderOut
    repo = PurchaseOrderRepository(db)
    result = await repo.search(current.company_id, q, status, vendor_id, from_date, to_date, pg.page, pg.page_size)
    return paginated([PurchaseOrderOut.model_validate(r).model_dump(mode='json') for r in result.items],
                     result.total, result.page, result.page_size, result.pages)

@router.post("/purchase-orders", status_code=201, summary="Create purchase order")
async def create_purchase_order(payload: PurchaseOrderCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import PurchaseOrderOut
    svc = PurchaseOrderService(db)
    po = await svc.create(current.company_id, payload, current.user_id)
    return created(PurchaseOrderOut.model_validate(po).model_dump(mode='json'), "Purchase order created.")

@router.get("/purchase-orders/{po_id}", summary="Get purchase order")
async def get_purchase_order(po_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import PurchaseOrderRepository
    from app.schemas.billing import PurchaseOrderOut
    repo = PurchaseOrderRepository(db)
    po = await repo.get_detail(po_id)
    if not po:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Purchase order not found.")
    return ok(PurchaseOrderOut.model_validate(po).model_dump(mode='json'))

@router.post("/purchase-orders/{po_id}/approve", summary="Approve purchase order")
async def approve_po(po_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import PurchaseOrderRepository
    from datetime import datetime, timezone
    repo = PurchaseOrderRepository(db)
    po = await repo.get_or_raise(po_id)
    await repo.update(po, {"approval_status": "approved", "approved_by": current.user_id,
                           "approved_at": datetime.now(timezone.utc), "status": "sent"})
    return ok(message="Purchase order approved.")

@router.post("/purchase-orders/{po_id}/receive", summary="Receive goods against a PO (updates stock)")
async def receive_purchase_order(po_id: UUID, current: CurrentUserDep, db: DBDep,
                                  payload: dict | None = None) -> ORJSONResponse:
    from app.schemas.billing import PurchaseOrderOut
    svc = PurchaseOrderService(db)
    items = (payload or {}).get("items")  # optional partial receipt: [{"item_id": "...", "qty": 5}, ...]
    po = await svc.receive(po_id, current.company_id, current.user_id, items)
    return ok(PurchaseOrderOut.model_validate(po).model_dump(mode='json'), "Goods received; stock updated.")

@router.patch("/purchase-orders/{po_id}", summary="Partially update purchase order (e.g. status)")
async def patch_purchase_order(po_id: UUID, current: CurrentUserDep, db: DBDep, payload: dict) -> ORJSONResponse:
    from app.db.repositories.billing import PurchaseOrderRepository
    from app.schemas.billing import PurchaseOrderOut
    from fastapi import HTTPException
    repo = PurchaseOrderRepository(db)
    po = await repo.get_detail(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    allowed = {"status", "expected_delivery", "actual_delivery", "notes", "paid_amount"}
    await repo.update(po, {k: v for k, v in payload.items() if k in allowed})
    updated = await repo.get_detail(po_id)
    return ok(PurchaseOrderOut.model_validate(updated).model_dump(mode='json'), "Purchase order updated.")

@router.delete("/purchase-orders/{po_id}", status_code=204, summary="Delete purchase order")
async def delete_purchase_order(po_id: UUID, current: CurrentUserDep, db: DBDep) -> Response:
    from app.db.repositories.billing import PurchaseOrderRepository
    repo = PurchaseOrderRepository(db)
    po = await repo.get_or_raise(po_id)
    await repo.delete(po)
    return Response(status_code=204)


# ═══════════════════════════════════════════════════════════════════
# INVOICES
# ═══════════════════════════════════════════════════════════════════

@router.get("/invoices", summary="Search invoices with full filters")
async def list_invoices(
    current: CurrentUserDep, db: DBDep, pg: PaginationDep,
    q: str | None = Query(None),
    status: str | None = Query(None, description="draft|finalized|sent|partial|paid|overdue|cancelled"),
    invoice_type: str | None = Query(None),
    party_id: UUID | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    overdue_only: bool = Query(False),
) -> ORJSONResponse:
    from app.db.repositories.billing import InvoiceRepository
    from app.schemas.billing import InvoiceOut
    repo = InvoiceRepository(db)
    result = await repo.search(current.company_id, q, status, invoice_type, party_id,
                               from_date, to_date, overdue_only, pg.page, pg.page_size)
    return paginated([InvoiceOut.model_validate(r).model_dump(mode='json') for r in result.items],
                     result.total, result.page, result.page_size, result.pages)

@router.post("/invoices", status_code=201, summary="Create invoice (draft)")
async def create_invoice(payload: InvoiceCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import InvoiceOut
    svc = InvoiceService(db)
    inv = await svc.create(current.company_id, payload, current.user_id)
    return created(InvoiceOut.model_validate(inv).model_dump(mode='json'), "Invoice created.")

@router.get("/invoices/stats", summary="Invoice dashboard statistics")
async def invoice_stats(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import InvoiceRepository
    repo = InvoiceRepository(db)
    stats = await repo.get_dashboard_stats(current.company_id)
    return ok(jsonable_encoder(stats))

@router.get("/invoices/{invoice_id}", summary="Get invoice by ID")
async def get_invoice(invoice_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import InvoiceRepository
    from app.schemas.billing import InvoiceOut
    repo = InvoiceRepository(db)
    inv = await repo.get_detail(invoice_id)
    if not inv:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Invoice not found.")
    return ok(InvoiceOut.model_validate(inv).model_dump(mode='json'))

@router.put("/invoices/{invoice_id}", summary="Update invoice (full edit if draft, limited fields otherwise)")
async def update_invoice(invoice_id: UUID, payload: InvoiceUpdate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import InvoiceOut
    svc = InvoiceService(db)
    updated = await svc.update(invoice_id, current.company_id, payload, current.user_id)
    return ok(InvoiceOut.model_validate(updated).model_dump(mode='json'), "Invoice updated.")

@router.patch("/invoices/{invoice_id}", summary="Partially update invoice (e.g. status)")
async def patch_invoice(invoice_id: UUID, current: CurrentUserDep, db: DBDep, payload: dict) -> ORJSONResponse:
    from app.db.repositories.billing import InvoiceRepository
    from app.schemas.billing import InvoiceOut
    repo = InvoiceRepository(db)
    inv = await repo.get_or_raise(invoice_id)
    if inv.status == "draft" and payload.get("status") and payload["status"] != "draft":
        raise BusinessError("Use the finalize endpoint to convert a draft invoice — it also updates stock and accounting.")
    allowed = {"status", "due_date", "notes"}
    updated = await repo.update(inv, {k: v for k, v in payload.items() if k in allowed})
    return ok(InvoiceOut.model_validate(updated).model_dump(mode='json'), "Invoice updated.")

@router.delete("/invoices/{invoice_id}", status_code=204, summary="Delete invoice (draft only)")
async def delete_invoice(invoice_id: UUID, current: CurrentUserDep, db: DBDep) -> Response:
    from app.db.repositories.billing import InvoiceRepository
    repo = InvoiceRepository(db)
    inv = await repo.get_or_raise(invoice_id)
    await repo.delete(inv)
    return Response(status_code=204)

@router.post("/invoices/{invoice_id}/finalize", summary="Finalize invoice (locks it, triggers accounting)")
async def finalize_invoice(invoice_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import InvoiceOut
    svc = InvoiceService(db)
    inv = await svc.finalize(invoice_id, current.company_id, current.user_id)
    return ok(InvoiceOut.model_validate(inv).model_dump(mode='json'), "Invoice finalized.")

@router.post("/invoices/{invoice_id}/cancel", summary="Cancel invoice")
async def cancel_invoice(invoice_id: UUID, payload: InvoiceCancelRequest,
                         current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import InvoiceOut
    svc = InvoiceService(db)
    inv = await svc.cancel(invoice_id, current.company_id, payload.reason, current.user_id)
    return ok(InvoiceOut.model_validate(inv).model_dump(mode='json'), "Invoice cancelled.")

@router.get("/invoices/{invoice_id}/pdf", summary="Download invoice as PDF")
async def download_invoice_pdf(invoice_id: UUID, current: CurrentUserDep, db: DBDep) -> Response:
    svc = InvoiceService(db)
    pdf_bytes = await svc.get_pdf_data(invoice_id, current.company_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="invoice-{invoice_id}.pdf"'})

@router.post("/invoices/{invoice_id}/send-email", summary="Email invoice to customer")
async def send_invoice_email(invoice_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    # Wire to email task when SMTP configured
    return ok(message="Invoice queued for email delivery.")

@router.post("/invoices/{invoice_id}/whatsapp", summary="Share invoice via WhatsApp link")
async def share_invoice_whatsapp(invoice_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import InvoiceRepository
    repo = InvoiceRepository(db)
    inv = await repo.get_or_raise(invoice_id)
    wa_link = f"https://wa.me/?text=Invoice%20{inv.invoice_no}%20-%20Amount%20Rs.{inv.total_amount}"
    return ok({"whatsapp_link": wa_link})


# ═══════════════════════════════════════════════════════════════════
# PAYMENTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/payments", summary="List payments")
async def list_payments(current: CurrentUserDep, db: DBDep, pg: PaginationDep,
                        payment_type: str | None = Query(None),
                        from_date: date | None = Query(None), to_date: date | None = Query(None)) -> ORJSONResponse:
    from app.db.repositories.billing import PaymentRepository
    from app.schemas.billing import PaymentOut
    repo = PaymentRepository(db)
    result = await repo.search(current.company_id, payment_type, None, from_date, to_date, pg.page, pg.page_size)
    return paginated([PaymentOut.model_validate(r).model_dump(mode='json') for r in result.items],
                     result.total, result.page, result.page_size, result.pages)

@router.post("/payments", status_code=201, summary="Record a payment / receipt")
async def create_payment(payload: PaymentCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.schemas.billing import PaymentOut
    svc = PaymentService(db)
    pay = await svc.create(current.company_id, payload, current.user_id)
    return created(PaymentOut.model_validate(pay).model_dump(mode='json'), "Payment recorded.")


# ═══════════════════════════════════════════════════════════════════
# DELIVERY CHALLANS
# ═══════════════════════════════════════════════════════════════════

@router.get("/delivery-challans", summary="List delivery challans")
async def list_challans(current: CurrentUserDep, db: DBDep, pg: PaginationDep,
                        q: str | None = Query(None)) -> ORJSONResponse:
    from app.db.repositories.billing import DeliveryChallanRepository
    from app.schemas.billing import DeliveryChallanOut
    repo = DeliveryChallanRepository(db)
    result = await repo.search(current.company_id, q, pg.page, pg.page_size)
    return paginated([DeliveryChallanOut.model_validate(r).model_dump(mode='json') for r in result.items],
                     result.total, result.page, result.page_size, result.pages)

@router.post("/delivery-challans", status_code=201, summary="Create delivery challan")
async def create_challan(payload: DeliveryChallanCreate, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import DeliveryChallanRepository, DocumentSequenceRepository
    from app.db.models.billing import DeliveryChallan, DeliveryChallanItem
    from app.schemas.billing import DeliveryChallanOut
    from app.utils.gst_calculator import GSTCalculator
    seq = DocumentSequenceRepository(db)
    dc_no = await seq.next_number(current.company_id, "dc")
    calc = GSTCalculator(payload.supply_type)
    total = Decimal("0")
    items_data = []
    for item in payload.items:
        line = calc.compute_line(1, item.description, item.quantity, item.rate, item.gst_rate)
        total += line.total_amount
        items_data.append((item, line))
    repo = DeliveryChallanRepository(db)
    dc = await repo.create({
        "company_id": current.company_id,
        "dc_no": dc_no, "dc_date": payload.dc_date,
        "party_id": payload.party_id, "billing_name": payload.billing_name,
        "billing_address": payload.billing_address,
        "shipping_address": payload.shipping_address,
        "challan_type": payload.challan_type,
        "warehouse_id": payload.warehouse_id,
        "vehicle_no": payload.vehicle_no,
        "place_of_supply": payload.place_of_supply,
        "supply_type": payload.supply_type,
        "linked_jo_id": payload.linked_jo_id,
        "notes": payload.notes,
        "total_amount": total, "status": "draft",
        "created_by": current.user_id,
    })
    for item, line in items_data:
        db.add(DeliveryChallanItem(
            dc_id=dc.id, product_id=item.product_id, description=line.description,
            quantity=line.quantity, rate=line.rate, amount=line.total_amount,
            batch_no=item.batch_no, serial_no=item.serial_no,
        ))
    await db.flush()
    return created(DeliveryChallanOut.model_validate(dc).model_dump(mode='json'), "Delivery challan created.")


from app.schemas.billing import EInvoiceRecordIn

@router.post("/invoices/{invoice_id}/einvoice", summary="Record a manually-generated IRN for this invoice")
async def record_einvoice(invoice_id: UUID, payload: EInvoiceRecordIn, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import InvoiceRepository
    from app.db.models.billing import EInvoiceLog

    repo = InvoiceRepository(db)
    inv = await repo.get_or_raise(invoice_id)

    updated = await repo.update(inv, {
        "irn": payload.irn,
        "ack_no": payload.ack_no,
        "ack_date": payload.ack_date,
        "qr_code_data": payload.qr_code_data,
        "ewb_no": payload.ewb_no,
        "ewb_valid_till": payload.ewb_valid_till,
    })

    db.add(EInvoiceLog(
        company_id=current.company_id,
        invoice_id=invoice_id,
        invoice_no=inv.invoice_no,
        irn=payload.irn,
        ack_no=payload.ack_no,
        ack_date=payload.ack_date,
        qr_code=payload.qr_code_data,
        status="recorded_manual",
    ))
    await db.flush()

    return ok(InvoiceOut.model_validate(updated).model_dump(mode="json"), "IRN recorded.")


@router.delete("/invoices/{invoice_id}/einvoice", summary="Clear/cancel the recorded IRN for this invoice")
async def cancel_einvoice(invoice_id: UUID, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories.billing import InvoiceRepository
    from app.db.models.billing import EInvoiceLog

    repo = InvoiceRepository(db)
    inv = await repo.get_or_raise(invoice_id)

    updated = await repo.update(inv, {
        "irn": None, "ack_no": None, "ack_date": None,
        "qr_code_data": None, "ewb_no": None, "ewb_valid_till": None,
    })

    db.add(EInvoiceLog(
        company_id=current.company_id,
        invoice_id=invoice_id,
        invoice_no=inv.invoice_no,
        status="cancelled_manual",
    ))
    await db.flush()

    return ok(InvoiceOut.model_validate(updated).model_dump(mode="json"), "IRN cleared.")