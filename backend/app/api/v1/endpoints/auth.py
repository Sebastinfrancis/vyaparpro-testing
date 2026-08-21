"""
Auth endpoints — Login · Logout · Refresh · ForgotPassword ·
ResetPassword · Change Password · 2FA Setup/Verify/Disable
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import ORJSONResponse
from slowapi.util import get_remote_address
from limits import parse as parse_rate_limit

from app.api.v1.dependencies import (
    CacheDep, CurrentUserDep, DBDep, PaginationDep,
)
from app.core.config import settings
from app.core.limiter import limiter
from app.core.exceptions import RateLimitExceededError
from app.core.limiter import limiter
from app.schemas import (
    ChangePasswordRequest, ForgotPasswordRequest, LoginRequest,
    RefreshRequest, RegisterRequest, ResetPasswordRequest,
    Setup2FAResponse, TokenResponse, UserOut, Verify2FARequest,
)
from app.services import AuthService
from app.utils.responses import created, ok

router = APIRouter()


@router.get(
    "/setup-status",
    summary="Whether this device already has a business set up (sign-up is one-time)",
)
async def setup_status(db: DBDep) -> ORJSONResponse:
    from app.db.repositories import CompanyRepository
    count = await CompanyRepository(db).count()
    return ok(data={"setup_complete": count > 0})


@router.post(
    "/register",
    summary="Public sign-up — creates a company, an Owner role, and the first user, then logs in",
    status_code=201,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: DBDep,
) -> ORJSONResponse:
    svc = AuthService(db)
    ip = request.client.host if request.client else None
    result = await svc.register(payload, ip=ip)
    return created(
        data={
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "token_type": "bearer",
            "expires_in": result["expires_in"],
            "company": {
                "id": str(result["company"].id),
                "legal_name": result["company"].legal_name,
                "gstin": result["company"].gstin,
            },
            "user": {
                "id": str(result["user"].id),
                "full_name": result["user"].full_name,
                "email": result["user"].email,
                "company_id": str(result["user"].company_id),
                "role_id": str(result["user"].role_id),
                "is_2fa_enabled": result["user"].is_2fa_enabled,
            },
        },
        message="Account created successfully.",
    )


@router.get(
    "/resolve-company",
    summary="Find which company/companies an email belongs to (used by the login screen)",
)
async def resolve_company(email: str, db: DBDep) -> ORJSONResponse:
    svc = AuthService(db)
    matches = await svc.resolve_companies(email)
    return ok(data={"matches": matches})


@router.post("/login", summary="Login with email + password (+ optional TOTP)")
async def login(
    payload: LoginRequest,
    request: Request,
    db: DBDep,
) -> ORJSONResponse:
    svc = AuthService(db)
    ip = request.client.host if request.client else None
    result = await svc.login(payload, ip=ip)
    return ok(
        data={
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id": str(result["user"].id),
                "full_name": result["user"].full_name,
                "email": result["user"].email,
                "company_id": str(result["user"].company_id),
                "role_id": str(result["user"].role_id),
                "is_2fa_enabled": result["user"].is_2fa_enabled,
            },
        },
        message="Login successful.",
    )


@router.post("/refresh", summary="Exchange a refresh token for a new access token")
async def refresh(payload: RefreshRequest, db: DBDep) -> ORJSONResponse:
    svc = AuthService(db)
    result = await svc.refresh(payload.refresh_token)
    return ok(data=result, message="Token refreshed.")


@router.post("/logout", summary="Revoke the current refresh token / session")
async def logout(
    payload: RefreshRequest,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = AuthService(db)
    await svc.logout(payload.refresh_token, current.user_id)
    return ok(message="Logged out successfully.")


@router.post("/change-password", summary="Change own password (invalidates all sessions)")
async def change_password(
    payload: ChangePasswordRequest,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = AuthService(db)
    await svc.change_password(
        user_id=current.user_id,
        company_id=current.company_id,
        current=payload.current_password,
        new=payload.new_password,
    )
    return ok(message="Password changed. Please log in again.")


_forgot_password_limit = parse_rate_limit(f"{settings.RATE_LIMIT_AUTH_PER_MINUTE}/minute")


def _check_forgot_password_rate_limit(request: Request) -> None:
    """
    Manual rate-limit check (dependency form, not decorator form).
    The decorator form (@limiter.limit) breaks FastAPI's parameter
    resolution in files using `from __future__ import annotations`
    (every endpoint file in this project) — it makes FastAPI stop
    recognizing payload/background_tasks/db as injectable params and
    treat them as required raw body fields instead, causing a 422.
    This dependency-based approach avoids that entirely.
    """
    key = get_remote_address(request)
    if not limiter.limiter.hit(_forgot_password_limit, key):
        raise RateLimitExceededError("Too many reset requests. Please try again in a minute.")


@router.post(
    "/forgot-password",
    summary="Request a password-reset email",
    dependencies=[Depends(_check_forgot_password_rate_limit)],
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: DBDep,
) -> ORJSONResponse:
    # Always return 200 to prevent user enumeration
    from app.db.repositories import UserRepository
    repo = UserRepository(db)
    
    user = await repo.get_by_email(payload.company_id, str(payload.email))

    if user:
        from app.core.security import create_reset_token
        from app.utils.email import send_reset_email
        token = create_reset_token(user.id, user.email)
        background_tasks.add_task(send_reset_email, user.email, token)

    return ok(message="If that email exists, a reset link has been sent.")


@router.post("/reset-password", summary="Set new password using reset token")
async def reset_password(payload: ResetPasswordRequest, db: DBDep) -> ORJSONResponse:
    from app.core.security import decode_token, hash_password
    from app.core.exceptions import TokenInvalidError
    from app.db.repositories import UserRepository
    from uuid import UUID

    claims = decode_token(payload.token, expected_type="reset")
    user_id = UUID(claims["sub"])
    repo = UserRepository(db)
    user = await repo.get_or_raise(user_id)
    # Ensure email in token matches
    if claims.get("email", "").lower() != user.email.lower():
        raise TokenInvalidError()
    from app.core.security import validate_password_strength
    from app.core.exceptions import PasswordValidationError
    errors = validate_password_strength(payload.new_password)
    if errors:
        raise PasswordValidationError("; ".join(errors))
    await repo.update(user, {"password_hash": hash_password(payload.new_password)})
    from app.db.repositories import UserSessionRepository
    await UserSessionRepository(db).revoke_all_for_user(user_id)
    return ok(message="Password reset successful. Please log in.")


# ── 2FA ───────────────────────────────────────────────────────────────────────

@router.post("/2fa/setup", summary="Generate TOTP secret and QR URI for authenticator app")
async def setup_2fa(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    svc = AuthService(db)
    result = await svc.setup_2fa(current.user_id)
    return ok(data=result, message="Scan the QR code with your authenticator app.")


@router.post("/2fa/verify", summary="Verify TOTP code and enable 2FA on account")
async def verify_2fa(
    payload: Verify2FARequest,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = AuthService(db)
    await svc.verify_2fa(current.user_id, payload.totp_code)
    return ok(message="2FA enabled successfully.")


@router.post("/2fa/disable", summary="Disable 2FA (requires valid TOTP code)")
async def disable_2fa(
    payload: Verify2FARequest,
    current: CurrentUserDep,
    db: DBDep,
) -> ORJSONResponse:
    svc = AuthService(db)
    await svc.disable_2fa(current.user_id, payload.totp_code)
    return ok(message="2FA disabled.")


@router.get("/me", summary="Get current authenticated user profile")
async def me(current: CurrentUserDep, db: DBDep) -> ORJSONResponse:
    from app.db.repositories import UserRepository

    repo = UserRepository(db)
    user = await repo.get_with_role(current.user_id)
    data = UserOut.model_validate(user).model_dump(mode="json")
    return ok(data=data)
