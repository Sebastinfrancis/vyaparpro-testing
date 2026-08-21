"""
VyaparPro — Plan definitions & limits.

The active plan is whatever `plan` code is baked into the signed activation
certificate (see app.core.license). These limits are enforced server-side
in UserService.create / RoleService.create so a single offline activation
can't be turned into an unlimited multi-user system just by adding users
or custom roles.

To change a limit, edit PLAN_LIMITS below — no other code changes needed.
Set max_users / max_custom_roles to None for "no limit".
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanConfig:
    code: str
    display_name: str
    storage_mode: str            # "offline" | "online"
    max_users: int | None        # total active users allowed, including the owner
    max_custom_roles: int | None # custom roles beyond the seeded system roles


PLAN_LIMITS: dict[str, PlanConfig] = {
    "demo": PlanConfig(
        code="demo",
        display_name="Demo",
        storage_mode="offline",
        max_users=1,
        max_custom_roles=0,
    ),
    "offline_monthly": PlanConfig(
        code="offline_monthly",
        display_name="Offline — Monthly",
        storage_mode="offline",
        max_users=2,
        max_custom_roles=2,
    ),
    "offline_yearly": PlanConfig(
        code="offline_yearly",
        display_name="Offline — Yearly",
        storage_mode="offline",
        max_users=3,
        max_custom_roles=3,
    ),
    "online_monthly": PlanConfig(
        code="online_monthly",
        display_name="Online (Cloud) — Monthly",
        storage_mode="online",
        max_users=10,
        max_custom_roles=5,
    ),
    "online_yearly": PlanConfig(
        code="online_yearly",
        display_name="Online (Cloud) — Yearly",
        storage_mode="online",
        max_users=10,
        max_custom_roles=10,
    ),
}

# Falls back to the most restrictive plan if the cert has no/unknown plan code —
# fail safe, not fail open.
DEFAULT_PLAN = PLAN_LIMITS["demo"]


def get_plan_config(plan_code: str | None) -> PlanConfig:
    if not plan_code:
        return DEFAULT_PLAN
    return PLAN_LIMITS.get(plan_code, DEFAULT_PLAN)