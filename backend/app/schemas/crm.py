"""VyaparPro — CRM Pydantic Schemas"""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import EmailStr, Field
from app.schemas import APIModel


class LeadCreate(APIModel):
    lead_name: str = Field(max_length=200)
    company_name: Optional[str] = None
    mobile: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    stage: str = "New"
    value: Decimal = Decimal("0")
    follow_up_date: Optional[date] = None
    ai_suggestion: Optional[str] = None
    notes: Optional[str] = None


class LeadUpdate(APIModel):
    lead_name: Optional[str] = None
    company_name: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[EmailStr] = None
    stage: Optional[str] = None
    value: Optional[Decimal] = None
    follow_up_date: Optional[date] = None
    ai_suggestion: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class LeadOut(APIModel):
    id: UUID
    company_id: UUID
    lead_name: str
    company_name: Optional[str]
    mobile: Optional[str]
    email: Optional[str]
    stage: str
    value: Decimal
    follow_up_date: Optional[date]
    ai_suggestion: Optional[str]
    notes: Optional[str]
    is_active: bool
    created_at: datetime