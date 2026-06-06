"""Session Management — list active sessions, revoke by id, revoke all."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse
from sqlalchemy import select

from app.api.v1.dependencies import CurrentUserDep, DBDep
from app.db.models import UserSession
from app.utils.responses import ok

router = APIRouter()


@router.get("", summary="List active sessions for current user")
async def list_sessions(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    now = datetime.now(timezone.utc)
    stmt = (
        select(UserSession)
        .where(
            UserSession.user_id == current.user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.created_at.desc())
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    data = [
        {
            "id": str(s.id),
            "ip_address": s.ip_address,
            "device_info": s.device_info,
            "created_at": s.created_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
        }
        for s in sessions
    ]
    return ok(data=data)


@router.delete("/{session_id}", summary="Revoke a specific session")
async def revoke_session(
    session_id: UUID,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    from app.db.repositories import UserSessionRepository
    repo = UserSessionRepository(db)
    session = await repo.get_or_raise(session_id)
    if session.user_id != current.user_id:
        from app.core.exceptions import PermissionDeniedError
        raise PermissionDeniedError("Cannot revoke another user's session.")
    await repo.update(session, {"revoked_at": datetime.now(timezone.utc)})
    return ok(message="Session revoked.")


@router.delete("", summary="Revoke ALL sessions for current user (force logout everywhere)")
async def revoke_all_sessions(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories import UserSessionRepository
    await UserSessionRepository(db).revoke_all_for_user(current.user_id)
    return ok(message="All sessions revoked.")
