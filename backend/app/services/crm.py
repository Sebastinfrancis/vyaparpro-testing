"""VyaparPro — CRM Service Layer"""
from __future__ import annotations
from typing import Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.crm import Lead
from app.db.repositories.crm import LeadRepository
from app.db.repositories import AuditLogRepository
from app.schemas.crm import LeadCreate, LeadUpdate


class CRMService:
    def __init__(self, session: AsyncSession) -> None:
        self.leads = LeadRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(self, company_id: UUID, payload: LeadCreate, user_id: UUID) -> Lead:
        data = payload.model_dump()
        data["company_id"] = company_id
        data["created_by"] = user_id
        lead = await self.leads.create(data)
        await self.audit.log(
            company_id=company_id, action="CREATE", module="crm",
            user_id=user_id, entity_type="crm_leads", entity_id=lead.id,
            entity_ref=lead.lead_name,
        )
        return lead

    async def update(self, lead_id: UUID, payload: LeadUpdate, company_id: UUID, user_id: UUID) -> Lead:
        lead = await self.leads.get_or_raise_scoped(lead_id, company_id=company_id)
        updated = await self.leads.update(lead, payload.model_dump(exclude_unset=True))
        await self.audit.log(
            company_id=company_id, action="UPDATE", module="crm",
            user_id=user_id, entity_type="crm_leads", entity_id=lead_id,
        )
        return updated

    async def search(self, company_id: UUID, **kwargs: Any):
        return await self.leads.search(company_id=company_id, **kwargs)