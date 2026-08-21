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

from app.db.models import GSTRate, Permission, Role, RolePermission, UnitOfMeasure

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


# ═══════════════════════════════════════════════════════════════════
# STANDARD ROLES — seeded per-company (roles are company-scoped, so this
# can't live in the global seed above; called from AuthService.register()
# at sign-up, from CompanyService.create() for any company created outside
# sign-up, and from POST /roles/seed-defaults to backfill older companies).
# ═══════════════════════════════════════════════════════════════════

STANDARD_ROLES: list[dict] = [
    {
        "role_name": "Owner", "role_level": 1,
        "description": "Full access to every module — the business owner or proprietor.",
        "permissions": "*",
    },
    {
        "role_name": "Admin", "role_level": 2,
        "description": "Full operational access, without deleting the company itself.",
        "modules": {
            "company": ["read", "update"],
            "branch": ["create", "read", "update", "delete", "access_all"],
            "user": ["create", "read", "update", "delete"],
            "role": ["create", "read", "update", "delete"],
            "customer": ["create", "read", "update", "delete"],
            "vendor": ["create", "read", "update", "delete"],
            "product": ["create", "read", "update", "delete"],
            "warehouse": ["create", "read", "update", "delete"],
            "inventory": ["read", "adjust", "transfer", "transfer_receive"],
            "invoice": ["create", "read", "update", "delete", "approve", "print"],
            "report": ["read", "export"],
            "accounting": ["create", "read", "update", "post", "reverse"],
            "gst": ["read", "file", "export"],
            "audit": ["read"],
        },
    },
    {
        "role_name": "Manager", "role_level": 3,
        "description": "Runs day-to-day branch operations — sales, purchases, stock, staff.",
        "modules": {
            "branch": ["read"], "user": ["read"],
            "customer": ["create", "read", "update"],
            "vendor": ["create", "read", "update"],
            "product": ["create", "read", "update"],
            "warehouse": ["read"],
            "inventory": ["read", "adjust", "transfer", "transfer_receive"],
            "invoice": ["create", "read", "update", "approve", "print"],
            "report": ["read", "export"], "gst": ["read"],
        },
    },
    {
        "role_name": "Accountant", "role_level": 3,
        "description": "Books, GST filing and financial reports — no stock or sales edits.",
        "modules": {
            "customer": ["read"], "vendor": ["read"],
            "invoice": ["read", "print"],
            "report": ["read", "export"],
            "accounting": ["create", "read", "update", "post", "reverse"],
            "gst": ["read", "file", "export"],
        },
    },
    {
        "role_name": "Sales Executive", "role_level": 4,
        "description": "Creates and prints sales invoices/quotations, manages customers.",
        "modules": {
            "customer": ["create", "read", "update"],
            "product": ["read"],
            "invoice": ["create", "read", "print"],
            "report": ["read"],
        },
    },
    {
        "role_name": "Cashier", "role_level": 4,
        "description": "Front-desk billing — creates and prints invoices, no edits after save.",
        "modules": {
            "customer": ["read"], "product": ["read"],
            "invoice": ["create", "read", "print"],
        },
    },
    {
        "role_name": "Storekeeper", "role_level": 4,
        "description": "Manages stock — products, warehouses, adjustments and transfers.",
        "modules": {
            "product": ["create", "read", "update"],
            "warehouse": ["read"],
            "inventory": ["read", "adjust", "transfer", "transfer_receive"],
            "report": ["read"],
        },
    },
    {
        "role_name": "Viewer", "role_level": 5,
        "description": "Read-only access — for auditors, investors or supervisory staff.",
        "modules": {
            "customer": ["read"], "vendor": ["read"], "product": ["read"],
            "warehouse": ["read"], "inventory": ["read"], "invoice": ["read"],
            "report": ["read"], "accounting": ["read"], "gst": ["read"], "audit": ["read"],
        },
    },
]


async def seed_standard_roles(session: AsyncSession, company_id, created_by=None) -> dict[str, Role]:
    """
    Idempotently seeds the 8 standard system roles for one company. Safe to
    call more than once — a role that already exists (matched by name) is
    left completely untouched, so any permission edits an owner already made
    to it aren't overwritten. Returns {role_name: Role} for every standard
    role that exists for this company after this call.
    """
    from sqlalchemy import select as _select

    existing = (await session.execute(
        _select(Role).where(Role.company_id == company_id)
    )).scalars().all()
    have = {r.role_name: r for r in existing}

    all_perms = (await session.execute(_select(Permission))).scalars().all()
    perms_by_code = {p.perm_code: p for p in all_perms}

    result: dict[str, Role] = dict(have)

    for spec in STANDARD_ROLES:
        name = spec["role_name"]
        if name in have:
            continue

        role = Role(
            company_id=company_id,
            role_name=name,
            role_level=spec["role_level"],
            description=spec["description"],
            is_system_role=True,
        )
        session.add(role)
        await session.flush()

        if spec.get("permissions") == "*":
            grant_codes = set(perms_by_code.keys())
        else:
            grant_codes = {
                f"{module}.{action}"
                for module, actions in spec["modules"].items()
                for action in actions
            }

        for code in grant_codes:
            perm = perms_by_code.get(code)
            if perm:
                session.add(RolePermission(role_id=role.id, perm_id=perm.id, granted_by=created_by))

        result[name] = role

    await session.flush()
    return result


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