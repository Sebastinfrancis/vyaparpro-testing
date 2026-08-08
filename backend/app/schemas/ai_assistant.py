"""app/schemas/ai_assistant.py — request/response models for the AI Assistant endpoint."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AIAskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="User's question, free text.")


class AIAskResponse(BaseModel):
    answer: str
    intent: str                 # "navigation" | "data_query" | "unknown"
    page: str | None = None     # frontend page id to navigate to, if applicable
    source: str                 # "knowledge_base" | "database" | "fallback"
