"""
VyaparPro — Business Service Layer
Orchestrates repositories, validates business rules, emits events.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AccountLockedError, AlreadyExistsError, InvalidCredentialsError,
    NotFoundError, PasswordValidationError, PermissionDeniedError,
    TwoFactorInvalidError, TwoFactorRequiredError,
)
from app.core.security import (
    create_access_token, create_refresh_token, decode_token,
    generate_totp_secret, get_totp_uri, hash_password,
    hash_token, validate_password_strength, verify_password, verify_totp,
)
from app.db.models import (
    Branch, Company, GSTRate, HSNCode, Organization, Party,
    Permission, Product, ProductCategory, Role, RolePermission,
    UnitOfMeasure, User, UserSession,
)
from app.db.repositories import (
    AuditLogRepository, BranchRepository, CompanyRepository,
    GSTRateRepository, HSNCodeRepository, OrganizationRepository,
    PartyRepository, PermissionRepository, ProductCategoryRepository,
    ProductRepository, RoleRepository, UnitOfMeasureRepository,
    UserRepository, UserSessionRepository,
)
from app.schemas import (
    BranchCreate, BranchUpdate, CategoryCreate, CategoryUpdate,
    CompanyCreate, CompanyUpdate, GSTRateOut, LoginRequest,
    OrganizationCreate, PartyCreate, PartyUpdate, ProductCreate,
    ProductUpdate, RoleCreate, RoleUpdate, TokenResponse, UserCreate,
    UserUpdate,
)


# ═══════════════════════════════════════════════════════════════════
# AUTH SERVICE
# ═══════════════════════════════════════════════════════════════════

class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.users = UserRepository(session)
        self.sessions = UserSessionRepository(session)
        self.perms = PermissionRepository(session)
        self.audit = AuditLogRepository(session)

    async def login(self, payload: LoginRequest, ip: str | None = None) -> dict[str, Any]:
        user = await self.users.get_by_email(payload.company_id, payload.email)
        if not user:
            raise InvalidCredentialsError()

        # Check lock
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            raise AccountLockedError()

        if not user.is_active:
            from app.core.exceptions import AccountInactiveError
            raise AccountInactiveError()

        if not verify_password(payload.password, user.password_hash):
            await self.users.increment_failed_logins(user.id)
            raise InvalidCredentialsError()

        # 2FA check
        if user.is_2fa_enabled:
            if not payload.totp_code:
                raise TwoFactorRequiredError()
            if not verify_totp(user.totp_secret, payload.totp_code):
                raise TwoFactorInvalidError()

        # Reset failures, update last login
        await self.users.reset_failed_logins(user.id)
        await self.users.update(user, {"last_login_at": datetime.now(timezone.utc), "last_login_ip": ip})

        # Load permissions
        perm_codes = await self.perms.get_user_permissions(user.id)

        # Create tokens
        access = create_access_token(
            user_id=user.id,
            company_id=user.company_id,
            role_id=user.role_id,
            branch_id=user.branch_id,
            scopes=perm_codes,
        )
        refresh = create_refresh_token(user.id)

        # Store session
        expires_at = datetime.now(timezone.utc)
        from datetime import timedelta
        from app.core.config import settings
        expires_at += timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        await self.sessions.create(
            {
                "user_id": user.id,
                "token_hash": hash_token(refresh),
                "ip_address": ip,
                "device_info": payload.device_info or {},
                "expires_at": expires_at,
            }
        )

        await self.audit.log(
            company_id=user.company_id,
            action="LOGIN",
            module="auth",
            user_id=user.id,
            ip_address=ip,
        )

        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": user,
        }

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        from app.core.config import settings
        from datetime import timedelta

        payload = decode_token(refresh_token, expected_type="refresh")
        user_id = UUID(payload["sub"])

        session = await self.sessions.get_by_token_hash(hash_token(refresh_token))
        if not session or session.revoked_at:
            from app.core.exceptions import TokenInvalidError
            raise TokenInvalidError("Session has been revoked.")

        user = await self.users.get_with_role(user_id)
        if not user or not user.is_active:
            from app.core.exceptions import TokenInvalidError
            raise TokenInvalidError()

        perm_codes = await self.perms.get_user_permissions(user.id)
        access = create_access_token(
            user_id=user.id,
            company_id=user.company_id,
            role_id=user.role_id,
            branch_id=user.branch_id,
            scopes=perm_codes,
        )
        return {
            "access_token": access,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def logout(self, refresh_token: str, user_id: UUID) -> None:
        session = await self.sessions.get_by_token_hash(hash_token(refresh_token))
        if session:
            await self.sessions.update(session, {"revoked_at": datetime.now(timezone.utc)})

    async def change_password(self, user_id: UUID, company_id: UUID, current: str, new: str) -> None:
        user = await self.users.get_or_raise(user_id)
        if not verify_password(current, user.password_hash):
            raise InvalidCredentialsError("Current password is incorrect.")
        errors = validate_password_strength(new)
        if errors:
            raise PasswordValidationError("; ".join(errors))
        await self.users.update(user, {"password_hash": hash_password(new)})
        await self.sessions.revoke_all_for_user(user_id)
        await self.audit.log(company_id=company_id, action="UPDATE", module="auth",
                             user_id=user_id, entity_ref="password_change")

    async def setup_2fa(self, user_id: UUID) -> dict[str, str]:
        user = await self.users.get_or_raise(user_id)
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, user.email)
        await self.users.update(user, {"totp_secret": secret})
        return {"secret": secret, "qr_uri": uri}

    async def verify_2fa(self, user_id: UUID, code: str) -> None:
        user = await self.users.get_or_raise(user_id)
        if not user.totp_secret or not verify_totp(user.totp_secret, code):
            raise TwoFactorInvalidError()
        await self.users.update(user, {"is_2fa_enabled": True})

    async def disable_2fa(self, user_id: UUID, code: str) -> None:
        user = await self.users.get_or_raise(user_id)
        if not verify_totp(user.totp_secret, code):
            raise TwoFactorInvalidError()
        await self.users.update(user, {"is_2fa_enabled": False, "totp_secret": None})


# ═══════════════════════════════════════════════════════════════════
# COMPANY SERVICE
# ═══════════════════════════════════════════════════════════════════

class CompanyService:
    def __init__(self, session: AsyncSession) -> None:
        self.companies = CompanyRepository(session)
        self.orgs = OrganizationRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(self, payload: CompanyCreate, created_by: UUID) -> Company:
        # Validate org exists
        org = await self.orgs.get(payload.org_id)
        if not org:
            raise NotFoundError("Organization not found.")

        # GSTIN uniqueness
        if payload.gstin:
            existing = await self.companies.get_by_gstin(payload.gstin)
            if existing:
                raise AlreadyExistsError(f"Company with GSTIN {payload.gstin} already exists.")

        data = payload.model_dump()
        data["created_by"] = created_by
        company = await self.companies.create(data)
        await self.audit.log(
            company_id=company.id, action="CREATE", module="company",
            user_id=created_by, entity_type="companies", entity_id=company.id,
            entity_ref=company.legal_name,
        )
        return company

    async def update(self, company_id: UUID, payload: CompanyUpdate, user_id: UUID) -> Company:
        company = await self.companies.get_or_raise(company_id)
        old = {k: getattr(company, k) for k in payload.model_fields_set}
        updated = await self.companies.update(company, payload.model_dump(exclude_unset=True))
        await self.audit.log(
            company_id=company_id, action="UPDATE", module="company",
            user_id=user_id, entity_type="companies", entity_id=company_id,
            old_values=old, changed_fields=list(payload.model_fields_set),
        )
        return updated

    async def list(self, query: str | None = None, page: int = 1, page_size: int = 20):
        return await self.companies.search(query=query, page=page, page_size=page_size)


# ═══════════════════════════════════════════════════════════════════
# BRANCH SERVICE
# ═══════════════════════════════════════════════════════════════════

class BranchService:
    def __init__(self, session: AsyncSession) -> None:
        self.branches = BranchRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(self, company_id: UUID, payload: BranchCreate, user_id: UUID) -> Branch:
        existing = await self.branches.get_by_code(company_id, payload.branch_code)
        if existing:
            raise AlreadyExistsError(f"Branch code '{payload.branch_code}' already exists.")
        data = payload.model_dump()
        data["company_id"] = company_id
        branch = await self.branches.create(data)
        await self.audit.log(
            company_id=company_id, action="CREATE", module="branch",
            user_id=user_id, entity_type="branches", entity_id=branch.id,
            entity_ref=branch.branch_name,
        )
        return branch

    async def update(self, branch_id: UUID, payload: BranchUpdate, company_id: UUID, user_id: UUID) -> Branch:
        branch = await self.branches.get_or_raise(branch_id)
        updated = await self.branches.update(branch, payload.model_dump(exclude_unset=True))
        await self.audit.log(
            company_id=company_id, action="UPDATE", module="branch",
            user_id=user_id, entity_type="branches", entity_id=branch_id,
        )
        return updated

    async def list_by_company(self, company_id: UUID) -> list[Branch]:
        return await self.branches.get_by_company(company_id)


# ═══════════════════════════════════════════════════════════════════
# USER SERVICE
# ═══════════════════════════════════════════════════════════════════

class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.users = UserRepository(session)
        self.roles = RoleRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(self, company_id: UUID, payload: UserCreate, created_by: UUID) -> User:
        # Check email uniqueness
        existing = await self.users.get_by_email(company_id, payload.email)
        if existing:
            raise AlreadyExistsError(f"User with email '{payload.email}' already exists.")

        # Validate password
        errors = validate_password_strength(payload.password)
        if errors:
            raise PasswordValidationError("; ".join(errors))

        # Validate role belongs to company
        role = await self.roles.get(payload.role_id)
        if not role or role.company_id != company_id:
            raise NotFoundError("Role not found in this company.")

        data = payload.model_dump(exclude={"password"})
        data["company_id"] = company_id
        data["email"] = payload.email.lower().strip()
        data["password_hash"] = hash_password(payload.password)

        user = await self.users.create(data)
        await self.audit.log(
            company_id=company_id, action="CREATE", module="user",
            user_id=created_by, entity_type="users", entity_id=user.id,
            entity_ref=user.email,
        )
        return user

    async def update(self, user_id: UUID, payload: UserUpdate, company_id: UUID, actor_id: UUID) -> User:
        user = await self.users.get_or_raise(user_id)
        if user.company_id != company_id:
            raise PermissionDeniedError()
        updated = await self.users.update(user, payload.model_dump(exclude_unset=True))
        await self.audit.log(
            company_id=company_id, action="UPDATE", module="user",
            user_id=actor_id, entity_type="users", entity_id=user_id,
        )
        return updated

    async def search(self, company_id: UUID, **kwargs: Any):
        return await self.users.search(company_id=company_id, **kwargs)

    async def get_with_role(self, user_id: UUID) -> User:
        user = await self.users.get_with_role(user_id)
        if not user:
            raise NotFoundError("User not found.")
        return user


# ═══════════════════════════════════════════════════════════════════
# ROLE SERVICE
# ═══════════════════════════════════════════════════════════════════

class RoleService:
    def __init__(self, session: AsyncSession) -> None:
        self.roles = RoleRepository(session)
        self.perms = PermissionRepository(session)
        self.audit = AuditLogRepository(session)
        self.session = session

    async def create(self, company_id: UUID, payload: RoleCreate, user_id: UUID) -> Role:
        existing = await self.roles.get_by(company_id=company_id, role_name=payload.role_name)
        if existing:
            raise AlreadyExistsError(f"Role '{payload.role_name}' already exists.")

        role = await self.roles.create({
            "company_id": company_id,
            "role_name": payload.role_name,
            "role_level": payload.role_level,
            "description": payload.description,
        })

        # Assign permissions
        if payload.permission_ids:
            for perm_id in payload.permission_ids:
                self.session.add(RolePermission(role_id=role.id, perm_id=perm_id, granted_by=user_id))
            await self.session.flush()

        return await self.roles.get_with_permissions(role.id)

    async def update(self, role_id: UUID, payload: RoleUpdate, company_id: UUID, user_id: UUID) -> Role:
        role = await self.roles.get_or_raise(role_id)
        if role.is_system_role:
            raise PermissionDeniedError("System roles cannot be modified.")

        updates = payload.model_dump(exclude={"permission_ids"}, exclude_unset=True)
        if updates:
            await self.roles.update(role, updates)

        if payload.permission_ids is not None:
            # Replace all permissions
            from sqlalchemy import delete
            await self.session.execute(
                delete(RolePermission).where(RolePermission.role_id == role_id)
            )
            for perm_id in payload.permission_ids:
                self.session.add(RolePermission(role_id=role_id, perm_id=perm_id, granted_by=user_id))
            await self.session.flush()

        return await self.roles.get_with_permissions(role_id)

    async def list_by_company(self, company_id: UUID) -> list[Role]:
        return await self.roles.get_by_company(company_id)

    async def list_permissions(self) -> list[Permission]:
        from sqlalchemy import select
        result = await self.session.execute(
            select(Permission).order_by(Permission.module, Permission.action)
        )
        return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════════════
# PARTY SERVICE
# ═══════════════════════════════════════════════════════════════════

class PartyService:
    def __init__(self, session: AsyncSession) -> None:
        self.parties = PartyRepository(session)
        self.audit = AuditLogRepository(session)
        self.session = session

    async def create(self, company_id: UUID, payload: PartyCreate, user_id: UUID) -> Party:
        # GSTIN uniqueness within company
        if payload.gstin:
            existing = await self.parties.get_by_gstin(company_id, payload.gstin)
            if existing:
                raise AlreadyExistsError(f"Party with GSTIN {payload.gstin} already exists.")

        # Auto-generate party code
        count = await self.parties.count(company_id=company_id)
        prefix = "C" if payload.party_type == "customer" else "V"
        party_code = f"{prefix}{str(count + 1).zfill(5)}"

        contacts_data = [c.model_dump() for c in payload.contacts]
        data = payload.model_dump(exclude={"contacts"})
        data["company_id"] = company_id
        data["party_code"] = party_code
        data["created_by"] = user_id

        party = await self.parties.create(data)

        # Create contacts
        from app.db.models import PartyContact
        for c in contacts_data:
            c["party_id"] = party.id
            self.session.add(PartyContact(**c))
        await self.session.flush()

        await self.audit.log(
            company_id=company_id, action="CREATE", module="party",
            user_id=user_id, entity_type="parties", entity_id=party.id,
            entity_ref=party.display_name,
        )
        return party

    async def update(self, party_id: UUID, payload: PartyUpdate, company_id: UUID, user_id: UUID) -> Party:
        party = await self.parties.get_or_raise(party_id)
        if party.company_id != company_id:
            raise PermissionDeniedError()
        updated = await self.parties.update(party, payload.model_dump(exclude_unset=True))
        await self.audit.log(
            company_id=company_id, action="UPDATE", module="party",
            user_id=user_id, entity_type="parties", entity_id=party_id,
        )
        return updated

    async def search(self, company_id: UUID, **kwargs: Any):
        return await self.parties.search(company_id=company_id, **kwargs)


# ═══════════════════════════════════════════════════════════════════
# PRODUCT SERVICE
# ═══════════════════════════════════════════════════════════════════

class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.products = ProductRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(self, company_id: UUID, payload: ProductCreate, user_id: UUID) -> Product:
        existing = await self.products.get_by_code(company_id, payload.product_code)
        if existing:
            raise AlreadyExistsError(f"Product code '{payload.product_code}' already exists.")
        if payload.barcode:
            dup = await self.products.get_by_barcode(company_id, payload.barcode)
            if dup:
                raise AlreadyExistsError(f"Barcode '{payload.barcode}' already in use.")

        data = payload.model_dump()
        data["company_id"] = company_id
        data["created_by"] = user_id
        product = await self.products.create(data)
        await self.audit.log(
            company_id=company_id, action="CREATE", module="inventory",
            user_id=user_id, entity_type="products", entity_id=product.id,
            entity_ref=product.product_name,
        )
        stmt = select(Product).where(Product.id == product.id).options(selectinload(Product.category),selectinload(Product.uom))
        result = await self.session.execute(stmt)
        product = result.scalar_one()
        return product

    async def update(self, product_id: UUID, payload: ProductUpdate, company_id: UUID, user_id: UUID) -> Product:
        product = await self.products.get_or_raise(product_id)
        if product.company_id != company_id:
            raise PermissionDeniedError()
        updated = await self.products.update(product, payload.model_dump(exclude_unset=True))
        await self.audit.log(
            company_id=company_id, action="UPDATE", module="inventory",
            user_id=user_id, entity_type="products", entity_id=product_id,
        )
        stmt = select(Product).where(Product.id == updated.id).options(selectinload(Product.category),selectinload(Product.uom))
        result = await self.session.execute(stmt)
        updated = result.scalar_one()
        return updated

    async def search(self, company_id: UUID, **kwargs: Any):
        return await self.products.search(company_id=company_id, **kwargs)


# ═══════════════════════════════════════════════════════════════════
# MASTER DATA SERVICES
# ═══════════════════════════════════════════════════════════════════

class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.cats = ProductCategoryRepository(session)

    async def create(self, company_id: UUID, payload: CategoryCreate) -> ProductCategory:
        data = payload.model_dump()
        data["company_id"] = company_id
        return await self.cats.create(data)

    async def update(self, cat_id: UUID, payload: CategoryUpdate, company_id: UUID) -> ProductCategory:
        cat = await self.cats.get_or_raise(cat_id)
        return await self.cats.update(cat, payload.model_dump(exclude_unset=True))

    async def tree(self, company_id: UUID) -> list[ProductCategory]:
        return await self.cats.get_tree(company_id)


class MasterDataService:
    def __init__(self, session: AsyncSession) -> None:
        self.uoms = UnitOfMeasureRepository(session)
        self.gst_rates = GSTRateRepository(session)
        self.hsn_codes = HSNCodeRepository(session)

    async def get_uoms(self) -> list[UnitOfMeasure]:
        return await self.uoms.get_all_active()

    async def get_gst_rates(self) -> list[GSTRate]:
        return await self.gst_rates.get_all_active()

    async def search_hsn(self, query: str) -> list[HSNCode]:
        return await self.hsn_codes.search(query)
