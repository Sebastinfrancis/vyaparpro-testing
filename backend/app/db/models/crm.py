"""VyaparPro — CRM ORM Models"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models import UUIDMixin, TimestampMixin, SoftDeleteMixin


class Lead(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "crm_leads"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    lead_name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(String(200))
    mobile: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(150))
    stage: Mapped[str] = mapped_column(String(30), default="New")
    value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    follow_up_date: Mapped[Optional[date]] = mapped_column(Date)
    ai_suggestion: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))