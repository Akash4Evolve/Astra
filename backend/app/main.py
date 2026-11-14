import os
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from astra_ml.alerts import Alert
from astra_ml.checkins import CheckIn, checkin_to_measurement
from astra_ml.models import Measurement, SourceType

from .audit import AuditEvent, AuditEventType
from .experimental import build_router as build_experimental_router, default_model_path
from .observability import REQUEST_ID, RequestLogMiddleware, configure_logging, logger
from .roles import HEADER as ROLE_HEADER, RoleMiddleware, current_role, roles_required_from_env
from .schemas import Action, ActionCreate, CheckInResult, DashboardOut, DeviceStatusOut, TrendsOut
from .services import evaluate_series
from .store import InMemoryStore
from .sync import SourceSyncState, SyncBatch, SyncLogEntry, SyncStatusOut
from .twin import TwinOut, build_twin
from .views import SUPPORTED_PARAMETERS, build_dashboard, build_device_status, build_trends

DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]  # Vite and React defaults
CHECKIN_SOURCES = {SourceType.MANUAL, SourceType.SIMULATED}


def _origins_from_env() -> list[str]:
    raw = os.getenv("ASTRA_CORS_ORIGINS")
    if raw is None:
        return list(DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def _require_aware(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"{name} must include a timezone, e.g. 2026-11-01T08:00:00Z")
    return value.astimezone(timezone.utc)


def create_app(
    store: InMemoryStore | None = None,
    clock: Callable[[], datetime] | None = None,
    stale_after: timedelta = timedelta(minutes=30),
    cors_origins: list[str] | None = None,
    twin_fresh_within: timedelta = timedelta(hours=36),
    ppg_model_path: Path | None = None,
    require_roles: bool | None = None,
) -> FastAPI:
    store = store or InMemoryStore()
    now = clock or (lambda: datetime.now(timezone.utc))
    origins = cors_origins if cors_origins is not None else _origins_from_env()
    if "*" in origins:
        raise ValueError("wildcard CORS origins are not allowed; list explicit origins")

    configure_logging()
    enforce_roles = roles_required_from_env() if require_roles is None else require_roles
    app = FastAPI(title="ASTRA API", version="1.0.0")
    # Starlette runs the last-added middleware first: CORS, then logging, then roles,
    # so a role refusal is still logged and still carries CORS headers.
    app.add_middleware(RoleMiddleware, require=enforce_roles)
    app.add_middleware(RequestLogMiddleware)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", ROLE_HEADER, REQUEST_ID],
            expose_headers=[REQUEST_ID],
        )
    logger.info("ASTRA API starting: roles %s, CORS origins %s",
                "ENFORCED" if enforce_roles else "recorded only", origins or "none")

    def audit(event_type: AuditEventType, actor: str, entity_type: str, entity_id: str | None = None,
              astronaut_id: str | None = None, **details) -> None:
        role = current_role.get()
        store.add_audit(AuditEvent(
            timestamp_utc=now(), event_type=event_type, actor=actor, astronaut_id=astronaut_id,
            role=role.value if role else None, entity_type=entity_type, entity_id=entity_id, details=details,
        ))
        # IDs only: no health values in the log.
        logger.info("audit %s %s=%s astronaut=%s role=%s", AuditEventType(event_type).value, entity_type,
                    entity_id or "-", astronaut_id or "-", role.value if role else "-")

    def ingest_measurements(items: list[Measurement], actor: str) -> tuple[list[Measurement], int, list[str]]:
        accepted, duplicates = store.add_measurements(items)
        per_astronaut = Counter(m.astronaut_id for m in accepted)
        dup_per_astronaut = Counter(m.astronaut_id for m in items) - per_astronaut
        for astronaut_id in sorted(set(per_astronaut) | set(dup_per_astronaut)):
            audit(AuditEventType.MEASUREMENTS_INGESTED, actor, "measurement_batch", None, astronaut_id,
                  accepted=per_astronaut[astronaut_id], duplicates=dup_per_astronaut[astronaut_id])
        raised: list[str] = []
        for astronaut_id, parameter in sorted({(m.astronaut_id, m.parameter) for m in accepted}):
            alert = evaluate_series(store, astronaut_id, parameter, clock=now)
            if alert is not None:
                raised.append(alert.alert_id)
        return accepted, duplicates, raised

    def ingest_checkin(checkin: CheckIn, actor: str) -> tuple[bool, list[str]]:
        if checkin.source_type not in CHECKIN_SOURCES:
            raise HTTPException(status_code=422, detail="check-ins must have source_type MANUAL or SIMULATED")
        if not store.add_checkin(checkin):
            return False, []
        store.add_measurements([checkin_to_measurement(checkin)])
        audit(AuditEventType.CHECKIN_RECORDED, actor, "checkin", str(checkin.checkin_id), checkin.astronaut_id)
        alert = evaluate_series(store, checkin.astronaut_id, "sleep_hours", clock=now)
        return True, [alert.alert_id] if alert else []

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc: RequestValidationError):
        details = [{"loc": [str(p) for p in e["loc"]], "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR",
                               "message": "Request payload failed validation",
                               "details": details}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail)}},
        )

    # ---------- experimental: window-level PPG quality gate ----------
    app.include_router(build_experimental_router(ppg_model_path or default_model_path(), audit))

    # ---------- measurements and alerts ----------
    @app.post("/api/v1/measurements")
    def ingest(measurements: list[Measurement]):
        accepted, duplicates, raised = ingest_measurements(measurements, "api_client")
        return {"accepted": len(accepted), "duplicates": duplicates, "alerts": raised}

    @app.get("/api/v1/alerts", response_model=list[Alert])
    def list_alerts(
        status: Literal["OPEN", "ACKNOWLEDGED"] | None = None,
        astronaut_id: str | None = None,
    ):
        return store.list_alerts(status=status, astronaut_id=astronaut_id)

    @app.get("/api/v1/alerts/{alert_id}", response_model=Alert)
    def get_alert(alert_id: str):
        alert = store.get_alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        return alert

    @app.post("/api/v1/alerts/{alert_id}/acknowledge", response_model=Alert)
    def acknowledge(alert_id: str):
        """Acknowledgement only means 'seen'. It is NOT medical clearance."""
        alert = store.get_alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        if alert.status == "OPEN":
            alert = alert.model_copy(update={"status": "ACKNOWLEDGED", "acknowledged_at": now()})
            store.save_alert(alert)
            audit(AuditEventType.ALERT_ACKNOWLEDGED, "api_client", "alert", alert.alert_id,
                  alert.astronaut_id, level=alert.level.value)
        return alert

    # ---------- check-ins ----------
    @app.post("/api/v1/check-ins", response_model=CheckInResult, status_code=201)
    def create_checkin(checkin: CheckIn, response: Response):
        created, alerts = ingest_checkin(checkin, "api_client")
        if not created:
            response.status_code = 200
            return CheckInResult(checkin=checkin, duplicate=True, alerts=[])
        return CheckInResult(checkin=checkin, duplicate=False, alerts=alerts)

    # ---------- actions (append-only) ----------
    @app.post("/api/v1/actions", response_model=Action, status_code=201)
    def create_action(body: ActionCreate):
        alert = store.get_alert(body.alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail=f"alert {body.alert_id} not found")
        action = Action(
            alert_id=alert.alert_id,
            astronaut_id=alert.astronaut_id,
            timestamp_utc=now(),
            action_type=body.action_type,
            note=body.note,
            follow_up_at=body.follow_up_at,
            outcome=body.outcome,
        )
        store.add_action(action)
        audit(AuditEventType.ACTION_RECORDED, "api_client", "action", action.action_id, action.astronaut_id,
              alert_id=action.alert_id, action_type=action.action_type.value, outcome=action.outcome)
        return action

    @app.get("/api/v1/actions", response_model=list[Action])
    def list_actions(
        alert_id: str | None = None,
        astronaut_id: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        return store.list_actions(alert_id=alert_id, astronaut_id=astronaut_id)[offset : offset + limit]

    # ---------- dashboard, trends, device status, twin ----------
    @app.get("/api/v1/astronauts/{astronaut_id}/dashboard", response_model=DashboardOut)
    def dashboard(astronaut_id: str):
        return build_dashboard(store, astronaut_id, now(), stale_after)

    @app.get("/api/v1/astronauts/{astronaut_id}/trends", response_model=TrendsOut)
    def trends(
        astronaut_id: str,
        parameter: list[str] | None = Query(default=None),
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = Query(500, ge=1, le=2000),
        offset: int = Query(0, ge=0),
    ):
        unknown = [p for p in (parameter or []) if p not in SUPPORTED_PARAMETERS]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown parameter {unknown}; supported: {list(SUPPORTED_PARAMETERS)}",
            )
        start = _require_aware(start, "start")
        end = _require_aware(end, "end")
        if start is not None and end is not None and start > end:
            raise HTTPException(status_code=422, detail="start must not be after end")
        return build_trends(store, astronaut_id, parameter, start, end, limit, offset)

    @app.get("/api/v1/astronauts/{astronaut_id}/twin", response_model=TwinOut)
    def twin(astronaut_id: str):
        return build_twin(store, astronaut_id, now(), twin_fresh_within)

    @app.get("/api/v1/devices/{device_id}/status", response_model=DeviceStatusOut)
    def device_status(device_id: str):
        status = build_device_status(store, device_id, now(), stale_after)
        if status is None:
            raise HTTPException(status_code=404, detail=f"device {device_id} not found")
        return status

    # ---------- delayed / offline sync ----------
    @app.post("/api/v1/sync", response_model=SyncLogEntry, status_code=201)
    def sync(batch: SyncBatch, response: Response):
        previous = store.get_sync(batch.batch_id)
        if previous is not None:
            store.count_duplicate_batch()
            audit(AuditEventType.SYNC_DUPLICATE_IGNORED, "sync", "sync_batch", batch.batch_id,
                  source_node=batch.source_node)
            response.status_code = 200
            return previous.model_copy(update={"status": "DUPLICATE_BATCH"})

        bad = [c for c in batch.checkins if c.source_type not in CHECKIN_SOURCES]
        if bad:
            raise HTTPException(status_code=422, detail="check-ins must have source_type MANUAL or SIMULATED")

        received = now()
        accepted, m_dup, alerts = ingest_measurements(batch.measurements, "sync")
        c_new = c_dup = 0
        for c in sorted(batch.checkins, key=lambda c: c.timestamp_utc):
            created, more = ingest_checkin(c, "sync")
            c_new += int(created)
            c_dup += int(not created)
            alerts += [a for a in more if a not in alerts]

        times = [m.timestamp_utc for m in batch.measurements] + [c.timestamp_utc for c in batch.checkins]
        oldest, newest = min(times), max(times)
        entry = SyncLogEntry(
            batch_id=batch.batch_id,
            source_node=batch.source_node,
            status="APPLIED",
            batch_created_at=batch.created_at,
            received_at=received,
            measurements_accepted=len(accepted),
            measurements_duplicate=m_dup,
            checkins_accepted=c_new,
            checkins_duplicate=c_dup,
            alerts=alerts,
            oldest_reading_at=oldest,
            newest_reading_at=newest,
            max_delivery_delay_seconds=max(0, int((received - oldest).total_seconds())),
        )
        store.add_sync(entry)
        audit(AuditEventType.SYNC_APPLIED, "sync", "sync_batch", batch.batch_id,
              source_node=batch.source_node, measurements_accepted=len(accepted),
              measurements_duplicate=m_dup, checkins_accepted=c_new, checkins_duplicate=c_dup,
              alerts=alerts)
        return entry

    @app.get("/api/v1/sync/log", response_model=list[SyncLogEntry])
    def sync_log(
        source_node: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        return store.list_sync(source_node)[offset : offset + limit]

    @app.get("/api/v1/sync/status", response_model=SyncStatusOut)
    def sync_status():
        entries = store.list_sync()
        sources: dict[str, SourceSyncState] = {}
        for e in reversed(entries):  # oldest first, so the last write per source wins
            prev = sources.get(e.source_node)
            sources[e.source_node] = SourceSyncState(
                source_node=e.source_node, last_sync_at=e.received_at, last_batch_id=e.batch_id,
                batches_applied=(prev.batches_applied if prev else 0) + 1,
            )
        return SyncStatusOut(
            generated_at=now(),
            batches_applied=len(entries),
            duplicate_batches_ignored=store.duplicate_batches(),
            last_sync_at=entries[0].received_at if entries else None,
            sources=sorted(sources.values(), key=lambda s: s.source_node),
        )

    # ---------- audit trail ----------
    @app.get("/api/v1/audit", response_model=list[AuditEvent])
    def audit_log(
        astronaut_id: str | None = None,
        event_type: AuditEventType | None = None,
        entity_id: str | None = None,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        events = store.list_audit(astronaut_id, event_type.value if event_type else None, entity_id)
        return events[offset : offset + limit]

    return app


app = create_app()
