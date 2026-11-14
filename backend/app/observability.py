"""Logging (batch 8).

One line per request: request ID, method, path, status, duration, declared role.
Health values are never logged: bodies and query strings are left out, and audit-trail
lines carry only event type, entity and astronaut ID. The audit trail (GET /api/v1/audit)
is the record of what changed; logs are for operating the service.

Level: ASTRA_LOG_LEVEL (default INFO). Every response carries X-Request-ID, taken from
the request if the client sent one, so a client error can be matched to a log line.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("astra")
REQUEST_ID = "X-Request-ID"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def configure_logging() -> None:
    """Give the 'astra' logger a handler once, unless the host app already configured one."""
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(os.getenv("ASTRA_LOG_LEVEL", "INFO").upper())
    logger.propagate = False


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        sent = request.headers.get(REQUEST_ID, "")
        rid = sent if _SAFE_ID.match(sent) else uuid.uuid4().hex[:12]
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("rid=%s %s %s failed", rid, request.method, request.url.path)
            raise
        ms = (time.perf_counter() - start) * 1000
        role = getattr(request.state, "role", None)
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(level, "rid=%s %s %s -> %d %.1fms role=%s", rid, request.method, request.url.path,
                   response.status_code, ms, role.value if role else "-")
        response.headers[REQUEST_ID] = rid
        return response
