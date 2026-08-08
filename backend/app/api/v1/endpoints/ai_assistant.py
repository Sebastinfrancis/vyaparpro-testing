"""
app/api/v1/endpoints/ai_assistant.py
──────────────────────────────────────────────────────────────────────────
Thin HTTP wrapper around app.ai_assistant.responder. Auth-protected like
every other endpoint (reuses CurrentUserDep / DBDep) so the assistant only
ever sees data the logged-in user's company is scoped to.

Register in main.py:
    app.include_router(ai_assistant_router, prefix=f"{prefix}/ai", tags=["AI Assistant"])
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from app.ai_assistant.responder import get_assistant_response
from app.api.v1.dependencies import CurrentUserDep, DBDep
from app.schemas.ai_assistant import AIAskRequest
from app.utils.responses import ok

router = APIRouter()


@router.post("/ask", summary="Ask the offline AI Assistant a question", response_model=None)
async def ask_assistant(payload: AIAskRequest, current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    result = await get_assistant_response(
        message=payload.message,
        db=db,
        company_id=current.company_id,
    )
    return ok(data=result.to_dict())
