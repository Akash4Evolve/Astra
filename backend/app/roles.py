"""Simple roles (batch 8).

Each request may say who is calling with the header `X-ASTRA-Role`. This is a DECLARED
role, not authentication: anyone who can reach the API can send any role. It exists so
that (a) the audit trail records which kind of client made each change, and (b) when
enforcement is on, a client cannot do things outside its job by mistake, such as the
ground station acknowledging an alert or a wristband recording an action.

Enforcement is off unless create_app(require_roles=True) or ASTRA_REQUIRE_ROLES=1.
When off, a role is still validated and recorded if sent.
Reads stay open to every caller (Swagger works without the header), except the audit trail.
"""
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from enum import Enum

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

HEADER = "X-ASTRA-Role"


class Role(str, Enum):
    DEVICE = "device"            # wristband / gateway: sends readings, offline batches, raw windows
    ASTRONAUT = "astronaut"      # crew member using the app
    CMO = "crew_medical_officer"  # onboard crew medical officer
    GROUND = "ground"            # mission control / flight surgeon: read only


ALL = frozenset(Role)
CREW = frozenset({Role.ASTRONAUT, Role.CMO})

# (method, path pattern, roles allowed). First match wins. Anything unlisted is open.
RULES: tuple[tuple[str, re.Pattern[str], frozenset[Role]], ...] = tuple(
    (method, re.compile(pattern), roles)
    for method, pattern, roles in (
        ("POST", r"^/api/v1/measurements$", frozenset({Role.DEVICE})),
        ("POST", r"^/api/v1/sync$", frozenset({Role.DEVICE})),
        ("POST", r"^/api/v1/experimental/ppg-quality$", frozenset({Role.DEVICE})),
        # A check-in is typed by the astronaut, in the app or on the band (relayed by the device).
        ("POST", r"^/api/v1/check-ins$", CREW | {Role.DEVICE}),
        ("POST", r"^/api/v1/alerts/[^/]+/acknowledge$", CREW),
        ("POST", r"^/api/v1/actions$", CREW),
        ("GET", r"^/api/v1/audit$", frozenset({Role.CMO, Role.GROUND})),
        ("GET", r"^/api/v1/sync/log$", frozenset({Role.DEVICE, Role.CMO, Role.GROUND})),
    )
)

current_role: ContextVar[Role | None] = ContextVar("astra_role", default=None)


def roles_required_from_env() -> bool:
    return os.getenv("ASTRA_REQUIRE_ROLES", "").strip().lower() in {"1", "true", "yes", "on"}


def allowed_roles(method: str, path: str) -> frozenset[Role] | None:
    for m, pattern, roles in RULES:
        if m == method and pattern.match(path):
            return roles
    return None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


class RoleMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, require: bool) -> None:
        super().__init__(app)
        self.require = require

    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get(HEADER)
        role: Role | None = None
        if raw is not None:
            try:
                role = Role(raw.strip().lower())
            except ValueError:
                return _error(400, "UNKNOWN_ROLE", f"{HEADER} must be one of {[r.value for r in Role]}")
        request.state.role = role
        if self.require and request.method != "OPTIONS":
            allowed = allowed_roles(request.method, request.url.path)
            if allowed is not None:
                if role is None:
                    return _error(403, "ROLE_REQUIRED",
                                  f"send {HEADER}: one of {sorted(r.value for r in allowed)}")
                if role not in allowed:
                    return _error(403, "FORBIDDEN_FOR_ROLE",
                                  f"role '{role.value}' may not {request.method} {request.url.path}; "
                                  f"allowed: {sorted(r.value for r in allowed)}")
        token = current_role.set(role)
        try:
            return await call_next(request)
        finally:
            current_role.reset(token)
