from __future__ import annotations
import hashlib
import json
import time
import base64
import platform
import subprocess
import httpx
from pathlib import Path
from datetime import datetime, timedelta
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from app.core.config import settings

LICENSE_FILE = Path.home() / ".vyaparpro" / "license.dat"
DEVICE_ID_CACHE = Path.home() / ".vyaparpro" / "device_id_cache.dat"


def get_hardware_fingerprint() -> str:
    """
    Returns a stable, non-reversible hash of this machine's identity.

    The raw machine id is cached to disk the first time it's successfully
    computed; every later call reuses that cached value instead of
    re-querying the OS. Without this, an intermittently slow/blocked
    PowerShell (or ioreg) call can silently fall back to a weaker, less
    stable id on some launches — which then no longer matches the
    fingerprint baked into the activation certificate, forcing re-activation
    on every restart even though nothing about the machine changed.
    """
    cached = _load_cached_raw_id()
    if cached:
        raw_id = cached
    else:
        raw_id = _raw_machine_id()
        _save_cached_raw_id(raw_id)
    return hashlib.sha256(raw_id.encode()).hexdigest()


def _load_cached_raw_id() -> str | None:
    try:
        if DEVICE_ID_CACHE.exists():
            cached = DEVICE_ID_CACHE.read_text().strip()
            if cached:
                return cached
    except Exception:
        pass
    return None


def _save_cached_raw_id(raw_id: str):
    try:
        DEVICE_ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
        DEVICE_ID_CACHE.write_text(raw_id)
    except Exception:
        pass  # if caching fails we just recompute next time — not fatal


def _raw_machine_id() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
                stderr=subprocess.DEVNULL, timeout=15,
            )
            machine_uuid = out.decode().strip()
            if machine_uuid and machine_uuid != "0" * 8:
                return machine_uuid
        elif system == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL, timeout=5,
            )
            for line in out.decode().splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        else:  # Linux
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                p = Path(path)
                if p.exists():
                    return p.read_text().strip()
    except Exception:
        pass
    # Last-resort fallback so the app doesn't crash on an unsupported setup —
    # weaker binding, but still consistent per install.
    import uuid as uuidlib
    return str(uuidlib.getnode())


def _b64d(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


class LicenseError(Exception):
    pass


class LicenseManager:
    def __init__(self):
        self._public_key: Ed25519PublicKey | None = None
        self._cached: dict | None = None

    @property
    def public_key(self) -> Ed25519PublicKey:
        # Loaded lazily, not in __init__ — main.py imports license_manager at
        # module load, before uvicorn binds a port, so a bad/missing key here
        # must never raise at import time or it takes down the entire API.
        if self._public_key is None:
            try:
                self._public_key = Ed25519PublicKey.from_public_bytes(
                    bytes.fromhex(settings.LICENSE_PUBLIC_KEY)
                )
            except Exception as e:
                raise LicenseError(f"Licensing is misconfigured on this build: {e}")
        return self._public_key

    def _verify_cert(self, cert: str) -> dict:
        try:
            body_b64, sig_b64 = cert.split(".")
            body = _b64d(body_b64)
            sig = _b64d(sig_b64)
            self.public_key.verify(sig, body)
            return json.loads(body)
        except (InvalidSignature, ValueError, KeyError) as e:
            raise LicenseError(f"License certificate is invalid or tampered: {e}")

    def load_local(self) -> dict | None:
        if not LICENSE_FILE.exists():
            return None
        try:
            stored = json.loads(LICENSE_FILE.read_text())
            payload = self._verify_cert(stored["certificate"])
            payload["_cert"] = stored["certificate"]
            payload["_last_check_in"] = stored.get("last_check_in", 0)
            return payload
        except Exception:
            return None

    def save_local(self, certificate: str):
        LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LICENSE_FILE.write_text(json.dumps({
            "certificate": certificate,
            "last_check_in": int(time.time()),
        }))

    async def activate(self, activation_code: str) -> dict:
        """
        Offline activation: activation_code is a certificate you (the
        developer) generated with generate_activation_code.py. Verified
        locally against LICENSE_PUBLIC_KEY — no network call.
        """
        code = activation_code.strip()
        payload = self._verify_cert(code)

        fp_now = get_hardware_fingerprint()
        if payload["device_fingerprint"] != fp_now:
            raise LicenseError(
                "This activation code was generated for a different device. "
                "Send us the Device ID shown below to get a matching code."
            )

        self.save_local(code)
        return payload

    async def _try_revalidate(self, license_key: str, fp: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{settings.LICENSE_SERVER_URL}/licenses/validate",
                    json={"license_key": license_key, "device_fingerprint": fp},
                )
            if r.status_code == 200:
                return r.json()["data"]["certificate"]
        except Exception:
            pass
        return None

    async def check(self) -> dict:
        """
        Call on every backend startup, and periodically in the background.
        Raises LicenseError if the app should refuse to run.
        """
        payload = self.load_local()
        if not payload:
            raise LicenseError("No active license found on this device. Please activate VyaparPro.")

        fp_now = get_hardware_fingerprint()
        if payload["device_fingerprint"] != fp_now:
            raise LicenseError(
                "This license certificate doesn't match this machine. "
                "If you moved VyaparPro to a new computer, activate the license here "
                "and deactivate it on the old machine from your account page."
            )

        now = time.time()
        cert_expired = payload["expires_at"] < now
        last_check_in = datetime.utcfromtimestamp(payload["_last_check_in"])
        grace_deadline = last_check_in + timedelta(days=settings.LICENSE_GRACE_DAYS)

        if cert_expired:
            fresh = await self._try_revalidate(payload["license_key"], fp_now)
            if fresh:
                self.save_local(fresh)
                return self._verify_cert(fresh)
            if datetime.utcnow() > grace_deadline:
                raise LicenseError(
                    "VyaparPro couldn't verify your license and the offline grace "
                    "period has ended. Please connect to the internet to continue."
                )
        return payload

    async def deactivate_this_device(self, license_key: str):
        fp = get_hardware_fingerprint()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{settings.LICENSE_SERVER_URL}/licenses/deactivate",
                    json={"license_key": license_key, "device_fingerprint": fp},
                )
        except Exception:
            pass  # no central server yet — local deactivation still proceeds
        if LICENSE_FILE.exists():
            LICENSE_FILE.unlink()

    async def list_devices(self) -> dict:
        payload = self.load_local()
        if not payload:
            raise LicenseError("No active license on this device.")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{settings.LICENSE_SERVER_URL}/licenses/devices",
                json={"license_key": payload["license_key"], "email": payload["customer_email"]},
            )
        if r.status_code != 200:
            raise LicenseError(r.json().get("message") or "Could not fetch device list.")
        data = r.json()["data"]
        this_fp = get_hardware_fingerprint()
        for d in data["devices"]:
            d["is_this_device"] = d["device_fingerprint"] == this_fp
        return data

    async def deactivate_device(self, device_id: str):
        payload = self.load_local()
        if not payload:
            raise LicenseError("No active license on this device.")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{settings.LICENSE_SERVER_URL}/licenses/devices/deactivate",
                json={"license_key": payload["license_key"], "email": payload["customer_email"],
                      "device_id": device_id},
            )
        if r.status_code != 200:
            raise LicenseError(r.json().get("message") or "Could not deactivate that device.")


license_manager = LicenseManager()