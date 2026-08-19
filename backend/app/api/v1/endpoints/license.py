from fastapi import APIRouter
from pydantic import BaseModel
from app.core.license import license_manager, LicenseError, get_hardware_fingerprint
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
        return ok(data={"valid": True, "plan": payload.get("plan"),
                         "expires_at": payload.get("expires_at")})
    except LicenseError as e:
        return ok(data={"valid": False, "message": str(e)})


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