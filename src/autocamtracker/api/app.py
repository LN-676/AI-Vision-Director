"""FastAPI application factory for local, read-only inspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import socket
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from autocamtracker.api.models import (
    EventPageResponse,
    SessionPageResponse,
    SessionResponse,
    SystemStatusResponse,
    VehiclePageResponse,
    VehicleResponse,
)
from autocamtracker.api.read_models import (
    ReadOnlyVehicleReader,
    TelemetryReader,
    decode_cursor,
    encode_cursor,
)
from autocamtracker.product import RELEASE_LABEL
from autocamtracker.edge_control.api import EdgeControlSettings, install_edge_control_routes
from autocamtracker.edge_control.repository import EdgeControlRepository


@dataclass(frozen=True, slots=True)
class ApiSettings:
    identity_db_path: Path = Path("outputs/vehicle_identity.sqlite3")
    telemetry_dir: Path = Path("outputs/telemetry")
    node_id: str = socket.gethostname()
    cors_allow_origins: tuple[str, ...] = ()
    edge_control: EdgeControlSettings | None = None


def create_app(
    settings: ApiSettings | None = None,
    *,
    edge_repository: EdgeControlRepository | None = None,
) -> FastAPI:
    config = settings or ApiSettings()
    vehicles = ReadOnlyVehicleReader(config.identity_db_path, config.node_id)
    telemetry = TelemetryReader(config.telemetry_dir)
    app = FastAPI(
        title="AI-Vision-Director Read-only API",
        summary="Local read-only inspection API",
        description=(
            "V3.0.0b2 Phase 1. This process opens SQLite in read-only mode and "
            "does not expose mutation endpoints."
        ),
        version="3.0.0b2",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    if config.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_allow_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Device-Token", "X-Edge-Node-ID"],
            expose_headers=[
                "X-AIVD-API-Timestamp-Ms",
                "X-AIVD-Frame-ID",
                "X-AIVD-Capture-Timestamp-Ms",
                "X-AIVD-Published-Timestamp-Ms",
                "X-AIVD-Encode-Duration-Ms",
                "X-AIVD-Pipeline-Latency-Ms",
                "X-AIVD-Source-Decode-Ms",
            ],
            max_age=600,
        )
    if config.edge_control is not None:
        app.state.edge_control_cors_origins = config.cors_allow_origins
        install_edge_control_routes(
            app,
            config.edge_control,
            repository=edge_repository,
        )

    @app.get(
        "/api/v3/system/status",
        response_model=SystemStatusResponse,
        tags=["system"],
        operation_id="getSystemStatus",
    )
    def system_status() -> SystemStatusResponse:
        checks = {
            "identity_database": "ready" if vehicles.available() else "unavailable",
            "telemetry": "ready" if telemetry.available() else "unavailable",
            "access_mode": "read_only",
        }
        return SystemStatusResponse(
            node_id=config.node_id,
            status="ready" if all(value != "unavailable" for value in checks.values()) else "degraded",
            observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            version_label=RELEASE_LABEL,
            deployment_mode="local",
            read_only=True,
            checks=checks,
        )

    @app.get(
        "/api/v3/vehicles",
        response_model=VehiclePageResponse,
        tags=["vehicles"],
        operation_id="listVehicles",
    )
    def list_vehicles(
        cursor: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> VehiclePageResponse:
        offset = _cursor(cursor)
        try:
            items, has_more = vehicles.list(offset=offset, limit=limit)
        except (FileNotFoundError, OSError, sqlite3.Error, ValueError) as error:
            raise HTTPException(status_code=503, detail="identity database unavailable") from error
        return VehiclePageResponse(
            items=items,
            next_cursor=encode_cursor(offset + limit) if has_more else None,
        )

    @app.get(
        "/api/v3/vehicles/{local_id}",
        response_model=VehicleResponse,
        tags=["vehicles"],
        operation_id="getVehicle",
    )
    def get_vehicle(local_id: int) -> VehicleResponse:
        if local_id <= 0:
            raise HTTPException(status_code=422, detail="local_id must be positive")
        try:
            vehicle = vehicles.get(local_id)
        except (FileNotFoundError, OSError, sqlite3.Error, ValueError) as error:
            raise HTTPException(status_code=503, detail="identity database unavailable") from error
        if vehicle is None:
            raise HTTPException(status_code=404, detail="vehicle not found")
        return vehicle

    @app.get(
        "/api/v3/sessions",
        response_model=SessionPageResponse,
        tags=["sessions"],
        operation_id="listSessions",
    )
    def list_sessions(
        cursor: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> SessionPageResponse:
        offset = _cursor(cursor)
        items, has_more = telemetry.list_sessions(offset=offset, limit=limit)
        return SessionPageResponse(
            items=items,
            next_cursor=encode_cursor(offset + limit) if has_more else None,
        )

    @app.get(
        "/api/v3/sessions/{session_id}",
        response_model=SessionResponse,
        tags=["sessions"],
        operation_id="getSession",
    )
    def get_session(session_id: str) -> SessionResponse:
        session = telemetry.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    @app.get(
        "/api/v3/events",
        response_model=EventPageResponse,
        tags=["events"],
        operation_id="listEvents",
    )
    def list_events(
        cursor: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        session_id: str | None = None,
        minimum_severity: str | None = None,
    ) -> EventPageResponse:
        offset = _cursor(cursor)
        try:
            items, has_more = telemetry.list_events(
                offset=offset,
                limit=limit,
                session_id=session_id,
                minimum_severity=minimum_severity,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return EventPageResponse(
            items=items,
            next_cursor=encode_cursor(offset + limit) if has_more else None,
        )

    return app


def _cursor(value: str | None) -> int:
    try:
        return decode_cursor(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
