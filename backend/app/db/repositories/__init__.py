"""
VyaparPro — Domain Repositories
Specialized query logic for each entity, on top of BaseRepository.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from app.db.models import (
    AuditLog, Branch, Company, GSTRate, HSNCode, Organization,
    Party, PartyContact, Permission, Product, ProductCategory,
    Role, RolePermission, UnitOfMeasure, User, UserSession,
)
from app.db.repositories.base import BaseRepository, Pagination


# ═══════════════════════════════════════════════════════════════════
# ORGANIZATION & COMPANY
# ═══════════════════════════════════════════════════════════════════

class OrganizationRepository(BaseRepository[Organization]):
    model = Organization


class CompanyRepository(BaseRepository[Company]):
    model = Company

    async def get_with_branches(self, company_id: UUID) -> Company | None:
        stmt = (
            select(Company)
            .where(Company.id == company_id)
            .options(selectinload(Company.branches))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_gstin(self, gstin: str) -> Company | None:
        return await self.get_by(gstin=gstin)

    async def search(
        self,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Pagination:
        stmt = select(Company).where(Company.is_active == True)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    Company.legal_name.ilike(like),
                    Company.trade_name.ilike(like),
                    Company.gstin.ilike(like),
                )
            )
        stmt = stmt.order_by(Company.legal_name)
        return await self.paginate(stmt, page, page_size)


class BranchRepository(BaseRepository[Branch]):
    model = Branch

    async def get_by_company(self, company_id: UUID, active_only: bool = True) -> list[Branch]:
        stmt = select(Branch).where(Branch.company_id == company_id)
        if active_only:
            stmt = stmt.where(Branch.is_active == True)
        stmt = stmt.order_by(Branch.branch_name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_code(self, company_id: UUID, branch_code: str) -> Branch | None:
        return await self.get_by(company_id=company_id, branch_code=branch_code)


# ═══════════════════════════════════════════════════════════════════
# USERS & PERMISSIONS
# ═══════════════════════════════════════════════════════════════════

class RoleRepository(BaseRepository[Role]):
    model = Role

    async def get_with_permissions(self, role_id: UUID) -> Role | None:
        stmt = (
            select(Role)
            .where(Role.id == role_id)
            .options(selectinload(Role.permissions))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_company(self, company_id: UUID) -> list[Role]:
        stmt = select(Role).where(Role.company_id == company_id).options(selectinload(Role.permissions)).order_by(Role.role_level, Role.role_name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class PermissionRepository(BaseRepository[Permission]):
    model = Permission

    async def get_by_codes(self, codes: list[str]) -> list[Permission]:
        stmt = select(Permission).where(Permission.perm_code.in_(codes))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_module(self, module: str) -> list[Permission]:
        stmt = select(Permission).where(Permission.module == module).order_by(Permission.perm_code)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_user_permissions(self, user_id: UUID) -> list[str]:
        """Return list of perm_codes for a user via their role."""
        stmt = (
            select(Permission.perm_code)
            .join(RolePermission, RolePermission.perm_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(User, User.role_id == Role.id)
            .where(User.id == user_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, company_id: UUID, email: str) -> User | None:
        return await self.get_by(company_id=company_id, email=email.lower().strip())

    async def get_with_role(self, user_id: UUID) -> User | None:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.role).selectinload(Role.permissions),
                selectinload(User.company),
                selectinload(User.branch),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        company_id: UUID,
        query: str | None = None,
        role_id: UUID | None = None,
        branch_id: UUID | None = None,
        active_only: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> Pagination:
        stmt = (
            select(User)
            .where(User.company_id == company_id)
            .options(selectinload(User.role).selectinload(Role.permissions), selectinload(User.branch))
        )
        if active_only:
            stmt = stmt.where(User.is_active == True)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(User.full_name.ilike(like), User.email.ilike(like), User.phone.ilike(like))
            )
        if role_id:
            stmt = stmt.where(User.role_id == role_id)
        if branch_id:
            stmt = stmt.where(User.branch_id == branch_id)
        stmt = stmt.order_by(User.full_name)
        return await self.paginate(stmt, page, page_size)

    async def increment_failed_logins(self, user_id: UUID) -> None:
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update
        from app.core.config import settings

        user = await self.get(user_id)
        if not user:
            return
        new_count = user.failed_logins + 1
        updates: dict = {"failed_logins": new_count}
        if new_count >= settings.MAX_LOGIN_ATTEMPTS:
            updates["locked_until"] = datetime.now(timezone.utc) + timedelta(
                minutes=settings.LOCKOUT_DURATION_MINUTES
            )
        await self.update(user, updates)

    async def reset_failed_logins(self, user_id: UUID) -> None:
        user = await self.get_or_raise(user_id)
        await self.update(user, {"failed_logins": 0, "locked_until": None})


class UserSessionRepository(BaseRepository[UserSession]):
    model = UserSession

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        return await self.get_by(token_hash=token_hash)

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        from datetime import datetime, timezone
        from sqlalchemy import update
        stmt = (
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)


# ═══════════════════════════════════════════════════════════════════
# PARTIES
# ═══════════════════════════════════════════════════════════════════

class PartyRepository(BaseRepository[Party]):
    model = Party

    async def search(
        self,
        company_id: UUID,
        party_type: str | None = None,
        query: str | None = None,
        city: str | None = None,
        active_only: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> Pagination:
        stmt = (
            select(Party)
            .where(Party.company_id == company_id)
            .options(selectinload(Party.contacts))
        )
        if active_only:
            stmt = stmt.where(Party.is_active == True)
        if party_type:
            stmt = stmt.where(or_(Party.party_type == party_type, Party.party_type == "both"))
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    Party.display_name.ilike(like),
                    Party.legal_name.ilike(like),
                    Party.gstin.ilike(like),
                    Party.phone.ilike(like),
                    Party.email.ilike(like),
                    Party.party_code.ilike(like),
                )
            )
        if city:
            stmt = stmt.where(Party.billing_city.ilike(f"%{city}%"))
        stmt = stmt.order_by(Party.display_name)
        return await self.paginate(stmt, page, page_size)

    async def get_by_gstin(self, company_id: UUID, gstin: str) -> Party | None:
        return await self.get_by(company_id=company_id, gstin=gstin)

    async def get_outstanding_summary(self, company_id: UUID) -> dict:
        from sqlalchemy import text
        stmt = text("""
            SELECT
                SUM(CASE WHEN balance_due > 0 THEN balance_due ELSE 0 END) AS total_receivable,
                COUNT(*) FILTER (WHERE status = 'overdue') AS overdue_count
            FROM invoices
            WHERE company_id = :cid AND status NOT IN ('cancelled','void','draft')
        """)
        result = (await self.session.execute(stmt, {"cid": company_id})).mappings().one_or_none()
        return dict(result) if result else {}


# ═══════════════════════════════════════════════════════════════════
# PRODUCTS & MASTER DATA
# ═══════════════════════════════════════════════════════════════════

class ProductCategoryRepository(BaseRepository[ProductCategory]):
    model = ProductCategory

    async def get_tree(self, company_id: UUID) -> list[ProductCategory]:
        stmt = (
            select(ProductCategory)
            .where(ProductCategory.company_id == company_id, ProductCategory.is_active == True)
            .order_by(ProductCategory.cat_name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class UnitOfMeasureRepository(BaseRepository[UnitOfMeasure]):
    model = UnitOfMeasure

    async def get_all_active(self) -> list[UnitOfMeasure]:
        stmt = select(UnitOfMeasure).where(UnitOfMeasure.is_active == True).order_by(UnitOfMeasure.uom_name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class GSTRateRepository(BaseRepository[GSTRate]):
    model = GSTRate

    async def get_all_active(self) -> list[GSTRate]:
        stmt = select(GSTRate).where(GSTRate.is_active == True).order_by(GSTRate.total_rate)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class HSNCodeRepository(BaseRepository[HSNCode]):
    model = HSNCode

    async def search(self, query: str, limit: int = 20) -> list[HSNCode]:
        like = f"%{query}%"
        stmt = (
            select(HSNCode)
            .where(or_(HSNCode.hsn_code.ilike(like), HSNCode.hsn_description.ilike(like)))
            .options(selectinload(HSNCode.gst_rate))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def search(
        self,
        company_id: UUID,
        query: str | None = None,
        cat_id: UUID | None = None,
        stock_status: str | None = None,
        is_service: bool | None = None,
        active_only: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> Pagination:
        stmt = (
            select(Product)
            .where(Product.company_id == company_id)
            .options(
                selectinload(Product.category),
                selectinload(Product.uom),
            )
        )
        if active_only:
            stmt = stmt.where(Product.is_active == True)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    Product.product_name.ilike(like),
                    Product.product_code.ilike(like),
                    Product.barcode.ilike(like),
                    Product.brand.ilike(like),
                    Product.hsn_code.ilike(like),
                )
            )
        if cat_id:
            stmt = stmt.where(Product.cat_id == cat_id)
        if is_service is not None:
            stmt = stmt.where(Product.is_service == is_service)
        stmt = stmt.order_by(Product.product_name)
        return await self.paginate(stmt, page, page_size)

    async def get_by_barcode(self, company_id: UUID, barcode: str) -> Product | None:
        return await self.get_by(company_id=company_id, barcode=barcode)

    async def get_by_code(self, company_id: UUID, product_code: str) -> Product | None:
        return await self.get_by(company_id=company_id, product_code=product_code)


# ═══════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════════

class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def log(
        self,
        company_id: UUID,
        action: str,
        module: str,
        user_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        entity_ref: str | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
        changed_fields: list[str] | None = None,
        ip_address: str | None = None,
        detail: str | None = None,
        actor_name: str | None = None,
    ) -> AuditLog:
        return await self.create(
            {
                "company_id": company_id,
                "user_id": user_id,
                "action": action,
                "module": module,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_ref": entity_ref,
                "old_values": old_values,
                "new_values": new_values,
                "changed_fields": changed_fields,
                "ip_address": ip_address,
                "detail": detail,
                "actor_name": actor_name,
            }
        )

    async def get_recent(
        self,
        company_id: UUID,
        module: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Pagination:
        stmt = (
            select(AuditLog)
            .where(AuditLog.company_id == company_id)
            .order_by(AuditLog.log_timestamp.desc())
        )
        if module:
            stmt = stmt.where(AuditLog.module == module)
        return await self.paginate(stmt, page, page_size)
