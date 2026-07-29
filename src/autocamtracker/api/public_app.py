"""Authenticated public API; no write route exists outside this factory."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    Security,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine
from starlette.concurrency import run_in_threadpool

from autocamtracker.api.auth import FirebaseTokenVerifier, Principal, TokenVerifier
from autocamtracker.api.models import (
    EventPageResponse,
    SessionPageResponse,
    SystemStatusResponse,
    VehiclePageResponse,
)
from autocamtracker.api.postgres_read import PostgresReadStore
from autocamtracker.api.read_models import decode_cursor, encode_cursor
from autocamtracker.api.secrets import PublicApiSettings
from autocamtracker.api.write_models import (
    AuditContext,
    RateLimiter,
    VehicleNotFound,
    VehiclePatchRequest,
    VehicleScopeDenied,
    VehicleWriteConflict,
    VehicleWriteResponse,
    VehicleWriteService,
)
from autocamtracker.cloud.security_store import (
    PostgresRateLimiter,
    PostgresVehicleWriteService,
)
from autocamtracker.cloud.advanced import (
    BenchmarkJobRequest,
    BenchmarkJobResponse,
    BenchmarkSubmissionService,
    ModelRegistryService,
    ModelRegistryConflict,
    ModelVersionRegistrationRequest,
    ModelVersionRegistrationResponse,
    ModelVersionStatusRequest,
    ModelVersionStatusResponse,
    ModelVersionNotFound,
    OrganizationScopeDenied,
)
from autocamtracker.product import RELEASE_LABEL


bearer = HTTPBearer(auto_error=False)
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class StatelessReadStore:
    """Empty read model for a cost-capped deployment without PostgreSQL."""

    def ready(self) -> bool:
        return True

    def list_vehicles(self, *, offset: int, limit: int):
        return [], False

    def list_sessions(self, *, offset: int, limit: int):
        return [], False

    def list_events(self, *, offset: int, limit: int, session_id: str | None):
        return [], False


class StatelessRateLimiter:
    """No persistent limiter is needed while every mutation is disabled."""

    def consume(self, subject: str, route: str):
        from autocamtracker.api.write_models import RateLimitDecision

        return RateLimitDecision(allowed=True, retry_after_seconds=0)


class StatelessVehicleWrites:
    def patch_vehicle(self, cloud_id, patch, context):
        raise RuntimeError("writes are disabled in stateless mode")


def create_public_app(
    settings: PublicApiSettings | None = None,
    *,
    token_verifier: TokenVerifier | None = None,
    vehicle_writes: VehicleWriteService | None = None,
    rate_limiter: RateLimiter | None = None,
    read_store: PostgresReadStore | None = None,
    benchmark_submissions: BenchmarkSubmissionService | None = None,
    model_registry: ModelRegistryService | None = None,
) -> FastAPI:
    config = settings or PublicApiSettings.from_env()
    owned_engine = None
    if (
        not config.stateless_mode
        and (vehicle_writes is None or rate_limiter is None or read_store is None)
    ):
        owned_engine = create_engine(config.database_url, pool_pre_ping=True)
    verifier = token_verifier or FirebaseTokenVerifier(config.firebase_project_id)
    writes = vehicle_writes or (
        StatelessVehicleWrites()
        if config.stateless_mode
        else PostgresVehicleWriteService(owned_engine)
    )
    limiter = rate_limiter or (
        StatelessRateLimiter()
        if config.stateless_mode
        else PostgresRateLimiter(
            owned_engine,
            config.rate_limit_requests,
            config.rate_limit_window_seconds,
        )
    )
    reads = read_store or (
        StatelessReadStore()
        if config.stateless_mode
        else PostgresReadStore(owned_engine)
    )
    app = FastAPI(
        title="AI-Vision-Director Public API",
        description=(
            "Authenticated V3 write API. Firebase token verification, RBAC, "
            "distributed rate limiting, optimistic concurrency, and audit are mandatory."
        ),
        version="3.0.0b1",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_allow_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["ETag", "X-Audit-ID"],
        max_age=600,
    )

    async def authenticated(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Security(bearer),
    ) -> Principal:
        source = request.client.host if request.client else "unknown"
        pre_auth = limiter.consume(f"ip:{source}", "AUTH:/api/v3")
        if not pre_auth.allowed:
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": str(pre_auth.retry_after_seconds)},
            )
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="valid Firebase bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return verifier.verify(credentials.credentials)
        except Exception as error:
            raise HTTPException(
                status_code=401,
                detail="invalid or revoked Firebase token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from error

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/api/v3/system/status",
        response_model=SystemStatusResponse,
        tags=["system"],
        operation_id="getSystemStatus",
    )
    def system_status() -> SystemStatusResponse:
        database_ready = reads.ready()
        return SystemStatusResponse(
            node_id="cloud",
            status="ready" if database_ready else "degraded",
            observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            version_label=RELEASE_LABEL,
            deployment_mode="cloud",
            read_only=True,
            checks={
                "postgresql": (
                    "disabled_cost_cap"
                    if config.stateless_mode
                    else ("ready" if database_ready else "unavailable")
                ),
                "access_mode": (
                    "stateless_read_only"
                    if config.stateless_mode
                    else "authenticated_writes"
                ),
            },
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
        items, has_more = reads.list_vehicles(offset=offset, limit=limit)
        return VehiclePageResponse(
            items=items,
            next_cursor=encode_cursor(offset + limit) if has_more else None,
        )

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
        items, has_more = reads.list_sessions(offset=offset, limit=limit)
        return SessionPageResponse(
            items=items,
            next_cursor=encode_cursor(offset + limit) if has_more else None,
        )

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
    ) -> EventPageResponse:
        offset = _cursor(cursor)
        items, has_more = reads.list_events(
            offset=offset,
            limit=limit,
            session_id=session_id,
        )
        return EventPageResponse(
            items=items,
            next_cursor=encode_cursor(offset + limit) if has_more else None,
        )

    @app.websocket("/ws/telemetry")
    async def telemetry_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin not in config.cors_allow_origins:
            await websocket.close(code=1008, reason="origin not allowed")
            return
        await websocket.accept()
        last_key: tuple[int, str] | None = None
        try:
            while True:
                items, _ = await run_in_threadpool(
                    reads.list_events,
                    offset=0,
                    limit=1,
                    session_id=None,
                )
                if items:
                    event = items[0]
                    key = (event.timestamp_ms, event.event)
                    if key != last_key:
                        await websocket.send_json(event.model_dump())
                        last_key = key
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            return

    @app.patch(
        "/api/v3/vehicles/{cloud_id}",
        response_model=VehicleWriteResponse,
        tags=["vehicles"],
        operation_id="patchVehicle",
    )
    def patch_vehicle(
        cloud_id: str,
        patch: VehiclePatchRequest,
        request: Request,
        response: Response,
        principal: Principal = Depends(authenticated),
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> VehicleWriteResponse:
        if config.stateless_mode:
            raise HTTPException(
                status_code=503,
                detail="writes are disabled in cost-capped stateless mode",
            )
        try:
            UUID(cloud_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="vehicle not found") from error
        if not principal.has_permission("vehicle:write"):
            raise HTTPException(status_code=403, detail="vehicle:write permission required")
        if not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
            raise HTTPException(status_code=400, detail="invalid Idempotency-Key")
        decision = limiter.consume(principal.uid, "PATCH:/api/v3/vehicles/{cloud_id}")
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        context = AuditContext(
            request_id=idempotency_key,
            actor=principal,
            source_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        try:
            result = writes.patch_vehicle(cloud_id, patch, context)
        except VehicleNotFound as error:
            raise HTTPException(status_code=404, detail="vehicle not found") from error
        except VehicleScopeDenied as error:
            raise HTTPException(status_code=403, detail="vehicle node scope denied") from error
        except VehicleWriteConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"message": "vehicle was modified", "current_updated_at": str(error)},
            ) from error
        response.headers["ETag"] = f'"{result.updated_at}"'
        response.headers["X-Audit-ID"] = result.audit_id
        return result

    @app.post(
        "/api/v3/benchmark-jobs",
        response_model=BenchmarkJobResponse,
        status_code=202,
        tags=["benchmarks"],
        operation_id="createBenchmarkJob",
    )
    def create_benchmark_job(
        job: BenchmarkJobRequest,
        principal: Principal = Depends(authenticated),
    ) -> BenchmarkJobResponse:
        if config.stateless_mode or benchmark_submissions is None:
            raise HTTPException(
                status_code=503,
                detail="cloud benchmark submission is not configured",
            )
        try:
            return benchmark_submissions.submit(job, principal)
        except OrganizationScopeDenied as error:
            raise HTTPException(
                status_code=403, detail="organization scope denied"
            ) from error
        except PermissionError as error:
            raise HTTPException(
                status_code=403, detail="benchmark:create permission required"
            ) from error
        except ModelVersionNotFound as error:
            raise HTTPException(status_code=404, detail="model version not found") from error

    @app.post(
        "/api/v3/model-versions",
        response_model=ModelVersionRegistrationResponse,
        status_code=201,
        tags=["models"],
        operation_id="registerModelVersion",
    )
    def register_model_version(
        model: ModelVersionRegistrationRequest,
        principal: Principal = Depends(authenticated),
    ) -> ModelVersionRegistrationResponse:
        if config.stateless_mode or model_registry is None:
            raise HTTPException(
                status_code=503,
                detail="model registry is not configured",
            )
        try:
            return model_registry.register(model, principal)
        except OrganizationScopeDenied as error:
            raise HTTPException(
                status_code=403, detail="organization scope denied"
            ) from error
        except PermissionError as error:
            raise HTTPException(
                status_code=403, detail="model:write permission required"
            ) from error
        except ModelRegistryConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.patch(
        "/api/v3/model-versions/{model_version_id}/status",
        response_model=ModelVersionStatusResponse,
        tags=["models"],
        operation_id="updateModelVersionStatus",
    )
    def update_model_version_status(
        model_version_id: str,
        status: ModelVersionStatusRequest,
        principal: Principal = Depends(authenticated),
    ) -> ModelVersionStatusResponse:
        if config.stateless_mode or model_registry is None:
            raise HTTPException(status_code=503, detail="model registry is not configured")
        try:
            return model_registry.update_status(model_version_id, status, principal)
        except (ValueError, ModelVersionNotFound) as error:
            raise HTTPException(status_code=404, detail="model version not found") from error
        except OrganizationScopeDenied as error:
            raise HTTPException(status_code=403, detail="organization scope denied") from error
        except PermissionError as error:
            raise HTTPException(
                status_code=403, detail="model:write permission required"
            ) from error

    if owned_engine is not None:
        @app.on_event("shutdown")
        def close_engine() -> None:
            owned_engine.dispose()

    return app


def _cursor(value: str | None) -> int:
    try:
        return decode_cursor(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
