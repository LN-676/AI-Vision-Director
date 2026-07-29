"""Public response models for the read-only V3 API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemStatusResponse(StrictResponse):
    node_id: str
    status: Literal["ready", "degraded"]
    observed_at: str
    version_label: str
    deployment_mode: Literal["local", "cloud"]
    read_only: Literal[True] = True
    checks: dict[str, str]


class VehicleResponse(StrictResponse):
    node_id: str
    local_id: int = Field(ge=1)
    cloud_id: str | None = None
    display_name: str
    class_name: str
    last_track_id: int | None
    last_frame_index: int = Field(ge=0)
    last_seen_at: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


class VehiclePageResponse(StrictResponse):
    items: list[VehicleResponse]
    next_cursor: str | None


class SessionResponse(StrictResponse):
    session_id: str
    started_at: str
    last_event_at: str
    event_count: int = Field(ge=0)
    source_file: str


class SessionPageResponse(StrictResponse):
    items: list[SessionResponse]
    next_cursor: str | None


class EventResponse(StrictResponse):
    schema_version: int = Field(ge=1)
    session_id: str
    event: str
    severity: str
    component: str
    reason_code: str | None
    timestamp_ms: int = Field(ge=0)
    data: dict[str, Any]


class EventPageResponse(StrictResponse):
    items: list[EventResponse]
    next_cursor: str | None
