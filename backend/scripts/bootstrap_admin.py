from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionFactory
from app.db.models import (
    Organization,
    Company,
    Role,
    User,
    Permission,
    RolePermission,
)
from app.core.security import hash_password


ADMIN_EMAIL = "admin@vyaparpro.local"
ADMIN_PASSWORD = "Admin@123"


async def run():
    async with AsyncSessionFactory() as session:

        # ========================
        # 1. Create Organization
        # ========================
        org = Organization(
            id=uuid4(),
            org_name="VyaparPro Org",
            org_type="company",
        )
        session.add(org)
        await session.flush()

        # ========================
        # 2. Create Company
        # ========================
        company = Company(
            id=uuid4(),
            org_id=org.id,
            legal_name="VyaparPro Demo Pvt Ltd",
            trade_name="VyaparPro",
            gstin=None,
            created_by=None,
        )
        session.add(company)
        await session.flush()

        # ========================
        # 3. Fetch permissions
        # ========================
        result = await session.execute(
            Permission.__table__.select()
        )
        permissions = result.fetchall()

        # ========================
        # 4. Create Admin Role
        # ========================
        role = Role(
            id=uuid4(),
            company_id=company.id,
            role_name="Super Admin",
            role_level=1,
            is_system_role=True,
        )
        session.add(role)
        await session.flush()

        # attach ALL permissions
        for perm in permissions:
            session.add(
                RolePermission(
                    role_id=role.id,
                    perm_id=perm.id,
                    granted_by=None,
                )
            )

        await session.flush()

        # ========================
        # 5. Create Admin User
        # ========================
        user = User(
            id=uuid4(),
            company_id=company.id,
            role_id=role.id,
            full_name="System Admin",
            email=ADMIN_EMAIL,
            phone="9999999999",
            password_hash=hash_password(ADMIN_PASSWORD),
            is_2fa_enabled=False,
        )

        session.add(user)
        await session.commit()

        print("\n✅ Bootstrap completed successfully!")
        print("====================================")
        print(f"Login Email: {ADMIN_EMAIL}")
        print(f"Password   : {ADMIN_PASSWORD}")
        print("====================================\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())