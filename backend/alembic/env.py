"""Alembic async migration environment."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.db.database import Base

# Import ALL models so Alembic sees them for autogenerate
from app.db.models import (  # noqa: F401
    Organization, Company, Branch,
    Role, Permission, RolePermission, User, UserSession,
    Party, PartyContact,
    ProductCategory, UnitOfMeasure, GSTRate, HSNCode,
    Product, ProductVariant,
    AuditLog,
)
from app.db.models.billing import (  # noqa: F401
    Quotation, QuotationItem, JobOrder, JobOrderItem,
    PurchaseOrder, PurchaseOrderItem, GoodsReceiptNote, GRNItem,
    DeliveryChallan, DeliveryChallanItem, Invoice, InvoiceItem,
    Payment, PaymentAllocation, DocumentSequence, EInvoiceLog,
)
from app.db.models.accounting import (  # noqa: F401
    AccountGroup, Account, CostCenter, JournalVoucher, JournalEntry,
    AccountLedger, BankReconciliation, GSTReturn, ITCLedger, FinancialYear,
)
from app.db.models.inventory import (  # noqa: F401
    Warehouse, WarehouseZone, InventoryStock, StockMovement,
    StockAdjustment, StockAdjustmentItem, StockTransfer, StockTransferItem,
    ProductBatch, SerialNumber, BarcodeLabel,
)

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.SYNC_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(settings.ASYNC_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
