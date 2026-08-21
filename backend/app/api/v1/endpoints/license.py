from fastapi import APIRouter
from pydantic import BaseModel
from app.api.v1.dependencies import CurrentUserDep, DBDep
from app.core.license import license_manager, LicenseError, get_hardware_fingerprint
from app.core.plans import get_plan_config
from app.utils.responses import ok

router = APIRouter()


class ActivateBody(BaseModel):
    license_key: str


@router.get("/device-id")
async def device_id():
    return ok(data={"device_id": get_hardware_fingerprint()})


@router.get("/status")
async def license_status():
    try:
        payload = await license_manager.check()
        plan_cfg = get_plan_config(payload.get("plan"))
        return ok(data={"valid": True, "plan": payload.get("plan"),
                         "plan_name": plan_cfg.display_name,
                         "expires_at": payload.get("expires_at")})
    except LicenseError as e:
        return ok(data={"valid": False, "message": str(e)})


@router.get("/plan-info")
async def plan_info(current: "CurrentUserDep", db: "DBDep"):
    """Authenticated: full plan details + live usage, for the Settings → Plan & Account screen."""
    from app.db.repositories import UserRepository, RoleRepository

    cert = license_manager.load_local() or {}
    plan_cfg = get_plan_config(cert.get("plan"))

    user_count = await UserRepository(db).count(company_id=current.company_id, is_active=True)
    custom_role_count = await RoleRepository(db).count(company_id=current.company_id, is_system_role=False)

    return ok(data={
        "plan_code": plan_cfg.code,
        "plan_name": plan_cfg.display_name,
        "storage_mode": plan_cfg.storage_mode,
        "expires_at": cert.get("expires_at"),
        "customer_email": cert.get("customer_email"),
        "max_users": plan_cfg.max_users,
        "current_users": user_count,
        "max_custom_roles": plan_cfg.max_custom_roles,
        "current_custom_roles": custom_role_count,
        "can_add_user": plan_cfg.max_users is None or user_count < plan_cfg.max_users,
        "can_add_role": plan_cfg.max_custom_roles is None or custom_role_count < plan_cfg.max_custom_roles,
    })


@router.post("/activate")
async def activate_license(body: ActivateBody):
    try:
        payload = await license_manager.activate(body.license_key)
        return ok(data={"valid": True, "plan": payload.get("plan")},
                   message="License activated on this device.")
    except LicenseError as e:
        return ok(data={"valid": False, "message": str(e)})


@router.post("/deactivate")
async def deactivate_license(body: ActivateBody):
    await license_manager.deactivate_this_device(body.license_key)
    return ok(message="Device deactivated.")


@router.get("/devices")
async def devices():
    try:
        data = await license_manager.list_devices()
        return ok(data=data)
    except LicenseError as e:
        return ok(data={"devices": [], "error": str(e)})


class DeactivateDeviceBody(BaseModel):
    device_id: str


@router.post("/devices/deactivate")
async def deactivate_device(body: DeactivateDeviceBody):
    try:
        await license_manager.deactivate_device(body.device_id)
        return ok(message="Device deactivated. A new device can now be activated on this license.")
    except LicenseError as e:
        return ok(data={"success": False, "message": str(e)})