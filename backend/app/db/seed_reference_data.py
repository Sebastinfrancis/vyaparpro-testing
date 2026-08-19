"""
Reference-data seeding for the desktop (SQLite) build.

On PostgreSQL this data is seeded once by scripts/init.sql when the Docker
volume is first created. The desktop build has no such init step, so this
does the equivalent in Python — permissions, GST rates, units of measure —
safe to call on every startup since each insert is skipped if already present.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GSTRate, Permission, UnitOfMeasure

PERMISSIONS = [
    ("company.create", "company", "create", "Create companies"),
    ("company.read", "company", "read", "View companies"),
    ("company.update", "company", "update", "Update company details"),
    ("company.delete", "company", "delete", "Deactivate companies"),
    ("branch.create", "branch", "create", "Create branches"),
    ("branch.read", "branch", "read", "View branches"),
    ("branch.update", "branch", "update", "Update branch"),
    ("branch.delete", "branch", "delete", "Deactivate branch"),
    ("branch.access_all", "branch", "access_all", "Act across all branches even when assigned to a specific branch (e.g. regional manager)"),
    ("user.create", "user", "create", "Create users"),
    ("user.read", "user", "read", "View users"),
    ("user.update", "user", "update", "Update users"),
    ("user.delete", "user", "delete", "Deactivate users"),
    ("role.create", "role", "create", "Create roles"),
    ("role.read", "role", "read", "View roles"),
    ("role.update", "role", "update", "Update roles"),
    ("role.delete", "role", "delete", "Delete roles"),
    ("customer.create", "customer", "create", "Create customers"),
    ("customer.read", "customer", "read", "View customers"),
    ("customer.update", "customer", "update", "Update customers"),
    ("customer.delete", "customer", "delete", "Deactivate customers"),
    ("vendor.create", "vendor", "create", "Create vendors"),
    ("vendor.read", "vendor", "read", "View vendors"),
    ("vendor.update", "vendor", "update", "Update vendors"),
    ("vendor.delete", "vendor", "delete", "Deactivate vendors"),
    ("product.create", "product", "create", "Create products"),
    ("product.read", "product", "read", "View products"),
    ("product.update", "product", "update", "Update products"),
    ("product.delete", "product", "delete", "Deactivate products"),
    ("warehouse.create", "warehouse", "create", "Create warehouses/stock points for a branch"),
    ("warehouse.read", "warehouse", "read", "View warehouses"),
    ("warehouse.update", "warehouse", "update", "Edit warehouse details"),
    ("warehouse.delete", "warehouse", "delete", "Deactivate a warehouse"),
    ("inventory.read", "inventory", "read", "View stock levels & valuation"),
    ("inventory.adjust", "inventory", "adjust", "Create & post stock adjustments"),
    ("inventory.transfer", "inventory", "transfer", "Create & dispatch inter-branch stock transfers"),
    ("inventory.transfer_receive", "inventory", "transfer_receive", "Receive/cancel inter-branch stock transfers"),
    ("invoice.create", "invoice", "create", "Create invoices"),
    ("invoice.read", "invoice", "read", "View invoices"),
    ("invoice.update", "invoice", "update", "Update invoices"),
    ("invoice.delete", "invoice", "delete", "Cancel invoices"),
    ("invoice.approve", "invoice", "approve", "Approve invoices"),
    ("invoice.print", "invoice", "print", "Print invoices"),
    ("report.read", "report", "read", "View reports"),
    ("report.export", "report", "export", "Export reports"),
    ("accounting.create", "accounting", "create", "Create accounts, account groups, and journal vouchers"),
    ("accounting.read", "accounting", "read", "View chart of accounts, ledgers, vouchers and accounting reports"),
    ("accounting.update", "accounting", "update", "Update accounts and account groups"),
    ("accounting.post", "accounting", "post", "Post a journal voucher to the ledger"),
    ("accounting.reverse", "accounting", "reverse", "Reverse a posted journal voucher"),
    ("gst.read", "gst", "read", "View GST summary, GSTR-1, GSTR-3B, HSN summary and ITC ledger"),
    ("gst.file", "gst", "file", "File GSTR-3B for a period (locks the period)"),
    ("gst.export", "gst", "export", "Download GST reports as PDF or export GSTR-1 JSON"),
    ("audit.read", "audit", "read", "View the audit log"),
]

UNITS_OF_MEASURE = [
    ("PCS", "Pieces", Decimal("1")),
    ("KG", "Kilograms", Decimal("1")),
    ("G", "Grams", Decimal("0.001")),
    ("LTR", "Litres", Decimal("1")),
    ("ML", "Millilitres", Decimal("0.001")),
    ("MTR", "Metres", Decimal("1")),
    ("CM", "Centimetres", Decimal("0.01")),
    ("BOX", "Box", Decimal("1")),
    ("PACK", "Pack", Decimal("1")),
    ("SET", "Set", Decimal("1")),
    ("PAIR", "Pair", Decimal("1")),
    ("NOS", "Numbers", Decimal("1")),
    ("ROLL", "Roll", Decimal("1")),
    ("SQ_MT", "Square Metres", Decimal("1")),
    ("CU_MT", "Cubic Metres", Decimal("1")),
    ("TON", "Metric Ton", Decimal("1000")),
    ("DOZEN", "Dozen", Decimal("12")),
]

GST_RATES = [
    ("Exempt", Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
    ("GST 5%", Decimal("5"), Decimal("2.5"), Decimal("2.5"), Decimal("5")),
    ("GST 12%", Decimal("12"), Decimal("6"), Decimal("6"), Decimal("12")),
    ("GST 18%", Decimal("18"), Decimal("9"), Decimal("9"), Decimal("18")),
    ("GST 28%", Decimal("28"), Decimal("14"), Decimal("14"), Decimal("28")),
]


async def seed_reference_data(session: AsyncSession) -> None:
    existing = (await session.execute(select(Permission.perm_code))).scalars().all()
    have = set(existing)
    for code, module, action, desc in PERMISSIONS:
        if code not in have:
            session.add(Permission(perm_code=code, module=module, action=action, description=desc))

    existing_uom = set((await session.execute(select(UnitOfMeasure.uom_code))).scalars().all())
    for code, name, factor in UNITS_OF_MEASURE:
        if code not in existing_uom:
            session.add(UnitOfMeasure(uom_code=code, uom_name=name, conversion_factor=factor))

    existing_rates = set((await session.execute(select(GSTRate.total_rate))).scalars().all())
    for name, total, cgst, sgst, igst in GST_RATES:
        if total not in existing_rates:
            session.add(GSTRate(rate_name=name, total_rate=total, cgst_rate=cgst, sgst_rate=sgst, igst_rate=igst))

    await session.commit()