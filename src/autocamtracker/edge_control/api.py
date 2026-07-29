"""FastAPI routes for local-first Edge command and state exchange."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json
from pathlib import Path
import os
import secrets
from time import time
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse

from autocamtracker.edge_control.models import (
    CommandAck,
    CommandCreate,
    EdgeCommand,
    EdgeNodeState,
    Heartbeat,
)
from autocamtracker.edge_control.repository import (
    EdgeControlRepository,
    SQLiteEdgeControlRepository,
)


@dataclass(frozen=True, slots=True)
class EdgeControlSettings:
    database_path: Path = Path("outputs/edge-control.sqlite3")
    preview_directory: Path = Path("outputs/edge-preview")
    device_token: str = ""
    offline_after_seconds: int = 6
    lease_seconds: int = 10

    @classmethod
    def from_env(cls) -> "EdgeControlSettings":
        return cls(
            database_path=Path(
                os.environ.get(
                    "AIVD_EDGE_CONTROL_DB", "outputs/edge-control.sqlite3"
                )
            ),
            preview_directory=Path(
                os.environ.get("AIVD_EDGE_PREVIEW_DIR", "outputs/edge-preview")
            ),
            device_token=os.environ.get("AIVD_EDGE_DEVICE_TOKEN", ""),
        )


def install_edge_control_routes(
    app: FastAPI,
    settings: EdgeControlSettings | None = None,
    *,
    repository: EdgeControlRepository | None = None,
) -> EdgeControlRepository:
    config = settings or EdgeControlSettings.from_env()
    store = repository or SQLiteEdgeControlRepository(config.database_path)
    app.state.edge_control_repository = store

    def valid_device_token(
        x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
    ) -> None:
        if (
            not config.device_token
            or x_device_token is None
            or not secrets.compare_digest(x_device_token, config.device_token)
        ):
            raise HTTPException(status_code=401, detail="valid Edge device token required")

    @app.get("/api/v3/edge/nodes", response_model=list[EdgeNodeState], tags=["edge"])
    def list_nodes() -> list[EdgeNodeState]:
        return store.list_nodes(config.offline_after_seconds)

    @app.get(
        "/api/v3/edge/nodes/{node_id}/state",
        response_model=EdgeNodeState,
        tags=["edge"],
    )
    def node_state(node_id: str) -> EdgeNodeState:
        state = store.get_node(node_id, config.offline_after_seconds)
        if state is None:
            raise HTTPException(status_code=404, detail="edge node not found")
        return state

    @app.get(
        "/api/v3/edge/preview/{view_name}",
        response_class=FileResponse,
        tags=["edge"],
    )
    def preview_frame(view_name: str) -> FileResponse:
        if view_name not in {"before", "after"}:
            raise HTTPException(status_code=404, detail="preview not found")
        path = config.preview_directory / f"{view_name}.jpg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="preview not ready")
        metadata: dict[str, object] = {}
        metadata_path = config.preview_directory / f"{view_name}.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            metadata = {}
        served_timestamp_ms = time() * 1000.0
        headers = {
            "Cache-Control": "no-store, max-age=0",
            "X-AIVD-API-Timestamp-Ms": f"{served_timestamp_ms:.3f}",
        }
        timing_headers = {
            "frame_id": "X-AIVD-Frame-ID",
            "capture_timestamp_ms": "X-AIVD-Capture-Timestamp-Ms",
            "published_timestamp_ms": "X-AIVD-Published-Timestamp-Ms",
            "encode_duration_ms": "X-AIVD-Encode-Duration-Ms",
            "pipeline_end_to_end_ms": "X-AIVD-Pipeline-Latency-Ms",
            "decode_duration_ms": "X-AIVD-Source-Decode-Ms",
        }
        for key, header in timing_headers.items():
            value = metadata.get(key)
            if value is not None:
                headers[header] = str(value)
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers=headers,
        )

    @app.post(
        "/api/v3/edge/nodes/{node_id}/commands",
        response_model=EdgeCommand,
        status_code=201,
        tags=["edge"],
    )
    def create_command(node_id: str, command: CommandCreate, response: Response) -> EdgeCommand:
        created = store.create_command(node_id, command)
        if (
            created.actor_uid != command.actor_uid
            or created.node_id != node_id
            or created.command_type != command.command_type
            or created.parameters != command.parameters
            or created.expires_at != command.expires_at
        ):
            raise HTTPException(status_code=409, detail="command_id already belongs to another command")
        if created.created_at < command.expires_at and created.status.value != "expired":
            response.status_code = 201
        else:
            response.status_code = 200
        return created

    @app.get(
        "/api/v3/edge/nodes/{node_id}/commands/claim",
        response_model=EdgeCommand | None,
        tags=["edge"],
    )
    def claim_command(
        node_id: str,
        _: None = Depends(valid_device_token),
        lease_seconds: int = Query(default=config.lease_seconds, ge=2, le=60),
    ) -> EdgeCommand | None:
        return store.claim_command(node_id, lease_seconds)

    @app.post(
        "/api/v3/edge/commands/{command_id}/ack",
        response_model=EdgeCommand,
        tags=["edge"],
    )
    def ack_command(
        command_id: UUID,
        ack: CommandAck,
        node_id: str = Header(alias="X-Edge-Node-ID"),
        _: None = Depends(valid_device_token),
    ) -> EdgeCommand:
        command = store.ack_command(command_id, node_id, ack)
        if command is None:
            raise HTTPException(status_code=404, detail="command not found")
        return command

    @app.post(
        "/api/v3/edge/nodes/{node_id}/heartbeat",
        response_model=EdgeNodeState,
        tags=["edge"],
    )
    def heartbeat(
        heartbeat: Heartbeat,
        node_id: str,
        _: None = Depends(valid_device_token),
    ) -> EdgeNodeState:
        return store.heartbeat(node_id, heartbeat)

    @app.websocket("/ws/control-state")
    async def control_state_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        allowed_origins = getattr(app.state, "edge_control_cors_origins", ())
        if allowed_origins and origin not in allowed_origins:
            await websocket.close(code=1008, reason="origin not allowed")
            return
        await websocket.accept()
        try:
            while True:
                nodes = store.list_nodes(config.offline_after_seconds)
                await websocket.send_json(
                    {
                        "type": "control_state",
                        "nodes": [
                            node.model_dump(mode="json") for node in nodes
                        ],
                    }
                )
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    return store
