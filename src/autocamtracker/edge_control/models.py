"""Strict wire models shared by the control API and Edge Agent."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    # JSON necessarily carries enums and timestamps as strings. Field-level
    # validators below keep command parameters strict while preserving a usable
    # wire contract.
    model_config = ConfigDict(extra="forbid")


class CommandType(str, Enum):
    START_TRACKING = "start_tracking"
    STOP_TRACKING = "stop_tracking"
    SET_TRACKING_MODE = "set_tracking_mode"
    SELECT_TARGET = "select_target"
    FIND_TARGET = "find_target"
    HOME = "home"
    EMERGENCY_STOP = "emergency_stop"


class CommandStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


TERMINAL_STATUSES = {
    CommandStatus.SUCCEEDED,
    CommandStatus.FAILED,
    CommandStatus.EXPIRED,
}


class CommandCreate(StrictModel):
    command_id: UUID
    actor_uid: str = Field(min_length=1, max_length=128)
    command_type: CommandType
    parameters: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime

    @model_validator(mode="after")
    def validate_parameters(self) -> "CommandCreate":
        allowed: dict[CommandType, set[str]] = {
            CommandType.START_TRACKING: set(),
            CommandType.STOP_TRACKING: set(),
            CommandType.HOME: set(),
            CommandType.EMERGENCY_STOP: set(),
            CommandType.SET_TRACKING_MODE: {"mode"},
            CommandType.SELECT_TARGET: {"target_gid"},
            CommandType.FIND_TARGET: {"target_gid"},
        }
        if set(self.parameters) != allowed[self.command_type]:
            expected = ", ".join(sorted(allowed[self.command_type])) or "no fields"
            raise ValueError(f"{self.command_type.value} parameters require exactly: {expected}")
        if "mode" in self.parameters and self.parameters["mode"] not in {
            "ai_tracking",
            "fixed_cut",
            "in_out_auto",
        }:
            raise ValueError("mode must be ai_tracking, fixed_cut, or in_out_auto")
        if "target_gid" in self.parameters and (
            type(self.parameters["target_gid"]) is not int
            or self.parameters["target_gid"] <= 0
        ):
            raise ValueError("target_gid must be a positive integer")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return self


class EdgeCommand(StrictModel):
    command_id: UUID
    node_id: str
    actor_uid: str
    command_type: CommandType
    parameters: dict[str, Any]
    priority: int
    status: CommandStatus
    created_at: datetime
    expires_at: datetime
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None


class CommandAck(StrictModel):
    status: CommandStatus
    result: dict[str, Any] | None = None
    error_message: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_transition(self) -> "CommandAck":
        if self.status not in {
            CommandStatus.EXECUTING,
            CommandStatus.SUCCEEDED,
            CommandStatus.FAILED,
        }:
            raise ValueError("ack status must be executing, succeeded, or failed")
        if self.status == CommandStatus.FAILED and not self.error_message:
            raise ValueError("failed ack requires error_message")
        return self


class CurrentTarget(StrictModel):
    gid: int | None = None
    display_name: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    tracking_state: str = "none"
    reacquiring: bool = False


class Heartbeat(StrictModel):
    app_version: str = Field(min_length=1, max_length=64)
    online: bool = True
    iphone_connected: bool
    dockkit_ready: bool
    tracking_running: bool
    tracking_mode: str = "ai_tracking"
    current_target: CurrentTarget | None = None
    available_targets: list[CurrentTarget] = Field(default_factory=list, max_length=100)
    fps: float | None = Field(default=None, ge=0.0)
    latency_ms: float | None = Field(default=None, ge=0.0)
    last_error: str | None = Field(default=None, max_length=2000)
    simulated: bool = False


class EdgeNodeState(Heartbeat):
    node_id: str
    last_heartbeat: datetime
    online: bool
    recent_commands: list[EdgeCommand] = Field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
