"""
app/ai_assistant/responder.py
──────────────────────────────────────────────────────────────────────────
Single entry point for the AI Assistant. This is the ONLY function the
rest of the application (the API endpoint) should ever call.

Flow:
  1. Classify the message (nav / data_query / unknown) via the current
     IntentEngine (see classifier.py — swappable).
  2. If it's a navigation/help question → answer from the local
     knowledge base (knowledge_base.NAV_KB), no DB access needed.
  3. If it's a database question → run the matching read-only handler
     from data_queries.py, scoped to the caller's own company_id.
  4. If nothing matched → return a friendly fallback message.

Everything runs on-device against data already available to the backend —
no cloud AI APIs, no paid services, no data leaves the server.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_assistant.classifier import get_intent_engine
from app.ai_assistant.data_queries import HANDLERS, party_lookup, branch_lookup, account_lookup
from app.ai_assistant.knowledge_base import DATA_KB, NAV_KB

_FALLBACK_ANSWER = (
    "I'm not sure about that yet — I can help with things like *\"How do I add a "
    "customer?\"*, *\"Where is GST Settings?\"*, *\"Show today's sales\"*, "
    "*\"Branch performance\"*, *\"Ledger of HDFC Bank\"* or *\"Open Purchase Orders\"*."
)


@dataclass(frozen=True)
class AssistantResponse:
    answer: str
    intent: str            # "navigation" | "data_query" | "party_lookup" | "unknown"
    page: str | None = None   # frontend page id to navigate to, if any
    source: str = "knowledge_base"  # "knowledge_base" | "database" | "fallback"

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "intent": self.intent,
            "page": self.page,
            "source": self.source,
        }


async def get_assistant_response(
    message: str,
    db: AsyncSession,
    company_id: UUID,
) -> AssistantResponse:
    engine = get_intent_engine()
    match = engine.classify(message)

    if match.intent_type == "navigation":
        entry = NAV_KB.get(match.intent_id)
        if entry:
            return AssistantResponse(
                answer=entry["answer"],
                intent="navigation",
                page=entry.get("page"),
                source="knowledge_base",
            )

    if match.intent_type == "data_query":
        entry = DATA_KB.get(match.intent_id)
        handler = HANDLERS.get(entry["handler"]) if entry else None
        if handler:
            try:
                answer = await handler(db, company_id)
            except Exception:
                # Never let a query hiccup surface as a 500 to the assistant UI.
                answer = (
                    "I couldn't pull that data just now — please try again, or "
                    "check the relevant screen directly."
                )
            return AssistantResponse(answer=answer, intent="data_query", source="database")

    if match.intent_type == "party_lookup":
        try:
            answer = await party_lookup(db, company_id, match.query or "")
        except Exception:
            answer = (
                "I couldn't look that up just now — please try again, or "
                "search directly in Customers / Vendors / CRM."
            )
        return AssistantResponse(answer=answer, intent="party_lookup", source="database")

    if match.intent_type == "branch_lookup":
        try:
            answer = await branch_lookup(db, company_id, match.query or "")
        except Exception:
            answer = (
                "I couldn't look that branch up just now — please try again, or "
                "check directly under **Branches**."
            )
        return AssistantResponse(answer=answer, intent="branch_lookup", source="database")

    if match.intent_type == "account_lookup":
        try:
            answer = await account_lookup(db, company_id, match.query or "")
        except Exception:
            answer = (
                "I couldn't look that account up just now — please try again, or "
                "check directly under **Ledger & Books**."
            )
        return AssistantResponse(answer=answer, intent="account_lookup", source="database")

    return AssistantResponse(answer=_FALLBACK_ANSWER, intent="unknown", source="fallback")
