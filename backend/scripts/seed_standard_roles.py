import asyncio
from uuid import uuid4, UUID

from app.db.database import AsyncSessionFactory
from app.db.models import Role, Permission, RolePermission
from sqlalchemy import select

# Your existing company (same one bootstrap_admin.py created / your app uses)
COMPANY_ID = UUID("34091ba5-aa42-40c8-9d22-e916cfefef6b")

ROLES = {
    "Admin": {
        "role_level": 1,
        "description": "Full administrative access to company, users, roles and all business modules. Unlike Super Admin, this role can be edited or reassigned.",
        "perms": [
            "company.create", "company.read", "company.update", "company.delete",
            "branch.create", "branch.read", "branch.update", "branch.delete",
            "user.create", "user.read", "user.update", "user.delete",
            "role.create", "role.read", "role.update", "role.delete",
            "customer.create", "customer.read", "customer.update", "customer.delete",
            "vendor.create", "vendor.read", "vendor.update", "vendor.delete",
            "product.create", "product.read", "product.update", "product.delete",
            "invoice.create", "invoice.read", "invoice.update", "invoice.delete", "invoice.approve", "invoice.print",
            "warehouse.create", "warehouse.read", "warehouse.update", "warehouse.delete",
            "inventory.read", "inventory.adjust", "inventory.transfer", "inventory.transfer_receive",
            "report.read", "report.export",
        ],
    },
    "Accountant": {
        "role_level": 3,
        "description": "Manages invoices, customers, vendors and financial reports.",
        "perms": [
            "invoice.create", "invoice.read", "invoice.update", "invoice.approve", "invoice.print",
            "customer.create", "customer.read", "customer.update",
            "vendor.create", "vendor.read", "vendor.update",
            "product.read", "report.read", "report.export",
            "company.read", "branch.read",
        ],
    },
    "Purchase Manager": {
        "role_level": 4,
        "description": "Manages vendors and purchase documents. Read-only on sales and reports.",
        "perms": [
            "vendor.create", "vendor.read", "vendor.update", "vendor.delete",
            "product.read", "product.update",
            "invoice.create", "invoice.read", "invoice.update", "invoice.print",
            "report.read", "company.read", "branch.read",
        ],
    },
    "Sales Executive": {
        "role_level": 5,
        "description": "Creates invoices/quotations and manages customers. No access to vendors, reports or settings.",
        "perms": [
            "invoice.create", "invoice.read", "invoice.update", "invoice.print",
            "customer.create", "customer.read", "customer.update",
            "product.read", "company.read", "branch.read",
        ],
    },
    "Cashier": {
        "role_level": 6,
        "description": "Handles point-of-sale billing and payments only. No access to vendors, reports or settings.",
        "perms": [
            "invoice.create", "invoice.read", "invoice.print",
            "customer.create", "customer.read",
            "product.read", "company.read", "branch.read",
        ],
    },
    "Inventory Manager": {
        "role_level": 4,
        "description": "Full control over products/stock. Read-only on invoices and vendors.",
        "perms": [
            "product.create", "product.read", "product.update", "product.delete",
            "vendor.create", "vendor.read", "vendor.update",
            "warehouse.create", "warehouse.read", "warehouse.update", "warehouse.delete",
            "inventory.read", "inventory.adjust", "inventory.transfer", "inventory.transfer_receive",
            "invoice.read", "report.read", "company.read", "branch.read",
        ],
    },
    "Branch Manager": {
        "role_level": 2,
        "description": "Oversees a single branch — staff, inventory, sales and purchases within it.",
        "perms": [
            "branch.read", "branch.update",
            "user.read", "user.update",
            "customer.create", "customer.read", "customer.update",
            "vendor.create", "vendor.read", "vendor.update",
            "product.create", "product.read", "product.update", "product.delete",
            "warehouse.read", "inventory.read", "inventory.transfer", "inventory.transfer_receive",
            "invoice.create", "invoice.read", "invoice.update", "invoice.approve", "invoice.print",
            "report.read", "report.export", "company.read",
        ],
    },
    "Viewer": {
        "role_level": 8,
        "description": "Read-only access across the system. Cannot create, edit or delete anything.",
        "perms": [
            "company.read", "branch.read", "customer.read", "vendor.read",
            "product.read", "invoice.read", "report.read", "report.export",
        ],
    },
}


async def run():
    async with AsyncSessionFactory() as session:
        # Look up permission IDs by code once
        result = await session.execute(select(Permission))
        perm_by_code = {p.perm_code: p.id for p in result.scalars().all()}

        for role_name, cfg in ROLES.items():
            existing = await session.execute(
                select(Role).where(Role.company_id == COMPANY_ID, Role.role_name == role_name)
            )
            if existing.scalar_one_or_none():
                print(f"⏭  '{role_name}' already exists — skipping.")
                continue

            role = Role(
                id=uuid4(),
                company_id=COMPANY_ID,
                role_name=role_name,
                role_level=cfg["role_level"],
                description=cfg["description"],
                is_system_role=False,
            )
            session.add(role)
            await session.flush()

            missing = [c for c in cfg["perms"] if c not in perm_by_code]
            if missing:
                print(f"⚠️  '{role_name}': permission codes not found, skipped: {missing}")

            for code in cfg["perms"]:
                if code in perm_by_code:
                    session.add(RolePermission(role_id=role.id, perm_id=perm_by_code[code], granted_by=None))

            print(f"✅ Created role '{role_name}' with {len(cfg['perms'])} permissions.")

        await session.commit()
        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(run())