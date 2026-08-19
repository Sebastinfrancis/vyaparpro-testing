"""
VyaparPro — Generic Base Repository
Provides type-safe CRUD operations, pagination, and filtering.
All domain repositories inherit from this.
"""
from __future__ import annotations

from typing import Any, Generic, Sequence, Type, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class Pagination:
    """Cursor/offset pagination result container."""
    __slots__ = ("items", "total", "page", "page_size", "pages")

    def __init__(
        self,
        items: list[Any],
        total: int,
        page: int,
        page_size: int,
    ) -> None:
        self.items = items
        self.total = total
        self.page = page
        self.page_size = page_size
        self.pages = max(1, -(-total // page_size))  # ceiling division


class BaseRepository(Generic[ModelT]):
    """Generic async repository for SQLAlchemy models."""

    model: Type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Create ────────────────────────────────────────────────────────
    async def create(self, obj_in: dict[str, Any]) -> ModelT:
        db_obj = self.model(**obj_in)
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    # ── Read ──────────────────────────────────────────────────────────
    async def get(self, id: UUID) -> ModelT | None:
        return await self.session.get(self.model, id)

    async def get_or_raise(self, id: UUID, exc: Exception | None = None) -> ModelT:
        obj = await self.get(id)
        if obj is None:
            raise exc or NotFoundError(f"{self.model.__name__} {id} not found.")
        return obj

    # ── Tenant-scoped variants ───────────────────────────────────────
    # Use these for any model with a company_id (or other tenant) column.
    # They filter company_id INTO the query, so a record from another
    # company can never be fetched/edited/deleted just by knowing its UUID.
    async def get_scoped(self, id: UUID, **scope: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(id=id, **scope)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_raise_scoped(self, id: UUID, exc: Exception | None = None, **scope: Any) -> ModelT:
        obj = await self.get_scoped(id, **scope)
        if obj is None:
            raise exc or NotFoundError(f"{self.model.__name__} {id} not found.")
        return obj

    async def update_by_id_scoped(self, id: UUID, obj_in: dict[str, Any], **scope: Any) -> ModelT:
        db_obj = await self.get_or_raise_scoped(id, **scope)
        return await self.update(db_obj, obj_in)

    async def soft_delete_scoped(self, id: UUID, **scope: Any) -> None:
        await self.get_or_raise_scoped(id, **scope)  # 404s on wrong tenant instead of silently no-op'ing
        stmt = (
            update(self.model)
            .where(self.model.id == id)  # type: ignore[attr-defined]
            .values(is_active=False)
        )
        await self.session.execute(stmt)

    async def delete_scoped(self, id: UUID, **scope: Any) -> None:
        db_obj = await self.get_or_raise_scoped(id, **scope)
        await self.session.delete(db_obj)
        await self.session.flush()

    async def get_by(self, **kwargs: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(**kwargs)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi_by(self, **kwargs: Any) -> list[ModelT]:
        stmt = select(self.model).filter_by(**kwargs)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all(self, stmt: Select | None = None) -> list[ModelT]:
        q = stmt if stmt is not None else select(self.model)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def paginate(
        self,
        stmt: Select,
        page: int = 1,
        page_size: int = 20,
    ) -> Pagination:
        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self.session.execute(count_stmt)).scalar_one()

        # Apply offset/limit
        offset = (page - 1) * page_size
        paginated = stmt.offset(offset).limit(page_size)
        result = await self.session.execute(paginated)
        items = list(result.scalars().all())

        return Pagination(items=items, total=total, page=page, page_size=page_size)

    # ── Update ────────────────────────────────────────────────────────
    async def update(self, db_obj: ModelT, obj_in: dict[str, Any]) -> ModelT:
        for field, value in obj_in.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def update_by_id(self, id: UUID, obj_in: dict[str, Any]) -> ModelT:
        db_obj = await self.get_or_raise(id)
        return await self.update(db_obj, obj_in)

    # ── Delete ────────────────────────────────────────────────────────
    async def delete(self, db_obj: ModelT) -> None:
        await self.session.delete(db_obj)
        await self.session.flush()

    async def soft_delete(self, id: UUID) -> None:
        """Set is_active=False instead of hard deleting."""
        stmt = (
            update(self.model)
            .where(self.model.id == id)  # type: ignore[attr-defined]
            .values(is_active=False)
        )
        await self.session.execute(stmt)

    # ── Existence checks ──────────────────────────────────────────────
    async def exists(self, **kwargs: Any) -> bool:
        stmt = select(func.count()).select_from(
            select(self.model).filter_by(**kwargs).subquery()
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return count > 0

    async def count(self, **kwargs: Any) -> int:
        stmt = select(func.count()).select_from(
            select(self.model).filter_by(**kwargs).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()
