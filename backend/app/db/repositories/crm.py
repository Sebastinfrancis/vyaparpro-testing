"""VyaparPro — CRM Repository"""
from __future__ import annotations
from uuid import UUID
from sqlalchemy import or_, select
from app.db.models.crm import Lead
from app.db.repositories.base import BaseRepository, Pagination


class LeadRepository(BaseRepository[Lead]):
    model = Lead

    async def search(
        self,
        company_id: UUID,
        query: str | None = None,
        stage: str | None = None,
        active_only: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> Pagination:
        stmt = select(Lead).where(Lead.company_id == company_id)
        if active_only:
            stmt = stmt.where(Lead.is_active == True)
        if stage:
            stmt = stmt.where(Lead.stage == stage)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(Lead.lead_name.ilike(like), Lead.company_name.ilike(like), Lead.mobile.ilike(like))
            )
        stmt = stmt.order_by(Lead.created_at.desc())
        return await self.paginate(stmt, page, page_size)