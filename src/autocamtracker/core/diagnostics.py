"""Module health snapshots and rule-based runtime diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from threading import Lock
from time import monotonic
from typing import Any

from autocamtracker.core.frame_data import FrameData


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAULT = "fault"
    IDLE = "idle"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ModuleHealth:
    component: str
    state: HealthState
    summary: str
    last_activity_monotonic: float
    metrics: dict[str, Any] = field(default_factory=dict)
    reason_code: str | None = None
    recommendation: str | None = None

    def age_seconds(self, now: float | None = None) -> float:
        return max(0.0, (monotonic() if now is None else now) - self.last_activity_monotonic)


class DiagnosticsService:
    """Keeps small in-memory health records; logs remain the event history."""

    def __init__(self, stale_after_seconds: float = 2.0) -> None:
        self.stale_after_seconds = max(0.1, float(stale_after_seconds))
        self._lock = Lock()
        self._modules: dict[str, ModuleHealth] = {}

    def update(
        self,
        component: str,
        state: HealthState,
        summary: str,
        *,
        metrics: dict[str, Any] | None = None,
        reason_code: str | None = None,
        recommendation: str | None = None,
    ) -> None:
        health = ModuleHealth(
            component=component,
            state=state,
            summary=summary,
            last_activity_monotonic=monotonic(),
            metrics=dict(metrics or {}),
            reason_code=reason_code,
            recommendation=recommendation,
        )
        with self._lock:
            self._modules[component] = health

    def observe_frame(self, frame: FrameData) -> None:
        latency = frame.latency_breakdown
        self.update(
            "source",
            HealthState.HEALTHY,
            f"frame {frame.source_frame_id if frame.source_frame_id is not None else 'local'} received",
            metrics={"source_fps": frame.source_fps, **frame.stream_counters},
        )
        self.update(
            "decoder",
            HealthState.HEALTHY,
            f"decode {frame.decode_time_ms:.1f} ms",
            metrics={"decode_ms": frame.decode_time_ms},
        )
        inference_state = HealthState.DEGRADED if frame.inference_time_ms >= 100.0 else HealthState.HEALTHY
        self.update(
            "detector",
            inference_state,
            f"{len(frame.detections)} detections · {frame.inference_time_ms:.1f} ms",
            metrics={"detections": len(frame.detections), "inference_ms": frame.inference_time_ms},
            reason_code="INFERENCE_SLOW" if inference_state is HealthState.DEGRADED else None,
            recommendation="Lower the model/input profile or inspect CPU/GPU load." if inference_state is HealthState.DEGRADED else None,
        )
        tracker_state = (
            HealthState.HEALTHY
            if frame.tracking_status == "tracking"
            else HealthState.DEGRADED
            if frame.selected_global_vehicle_id is not None or frame.selected_local_track_id is not None
            else HealthState.IDLE
        )
        self.update(
            "tracker",
            tracker_state,
            f"{frame.tracking_status} · lost {frame.lost_frames}",
            metrics={"lost_frames": frame.lost_frames, "lid": frame.selected_local_track_id},
            reason_code="TARGET_NOT_LOCKED" if tracker_state is HealthState.DEGRADED else None,
        )
        self.update(
            "reid",
            HealthState.HEALTHY if frame.motor_safe_to_track else HealthState.DEGRADED,
            f"{frame.reid_confidence_level} · score {frame.reacquire_score:.2f}",
            metrics={"gid": frame.selected_global_vehicle_id, "score": frame.reacquire_score},
            reason_code=(
                frame.identity_decision.reason_code.value
                if frame.identity_decision is not None and not frame.motor_safe_to_track
                else None
            ),
        )
        self.update(
            "pipeline",
            HealthState.DEGRADED if frame.pipeline_time_ms >= 100.0 else HealthState.HEALTHY,
            f"pipeline {frame.pipeline_time_ms:.1f} ms",
            metrics={
                "pipeline_ms": frame.pipeline_time_ms,
                "end_to_end_ms": latency.end_to_end_ms if latency is not None else None,
            },
        )
        self.update(
            "gmc",
            HealthState.HEALTHY if frame.global_motion is not None else HealthState.IDLE,
            f"global motion {'available' if frame.global_motion is not None else 'inactive'} · {frame.gmc_time_ms:.1f} ms",
            metrics={"gmc_ms": frame.gmc_time_ms},
        )
        self.update("framing", HealthState.HEALTHY, "framing decision active")

    def observe_server(self, server: Any, motor_armed: bool) -> None:
        clients = int(server.client_count)
        self.update(
            "websocket",
            HealthState.HEALTHY if server.is_running and clients else HealthState.DEGRADED if server.is_running else HealthState.FAULT,
            f"{'running' if server.is_running else 'stopped'} · {clients} client(s)",
            metrics={"clients": clients},
            reason_code="NO_CLIENT" if server.is_running and clients == 0 else "SERVER_STOPPED" if not server.is_running else None,
            recommendation="Open the iPhone app and verify local-network connectivity." if server.is_running and clients == 0 else None,
        )
        status = server.motor_status
        if status is None:
            self.update(
                "dockkit",
                HealthState.UNKNOWN if clients == 0 else HealthState.DEGRADED,
                "no motor status",
                reason_code="MOTOR_STATUS_MISSING",
                recommendation="Verify DockKit pairing and Manual Mode on iPhone.",
            )
        else:
            self.update(
                "dockkit",
                HealthState.HEALTHY if status.ready else HealthState.FAULT,
                f"docked={status.docked} manual={status.manual_ready}",
                metrics={"ready": status.ready, "last_error": status.last_error},
                reason_code="DOCKKIT_NOT_READY" if not status.ready else None,
                recommendation="Check accessory power, Bluetooth, and Manual Mode." if not status.ready else None,
            )
        self.update(
            "motor_control",
            HealthState.HEALTHY if motor_armed and server.motor_ready else HealthState.IDLE if not motor_armed else HealthState.DEGRADED,
            f"armed={motor_armed} ready={server.motor_ready}",
        )

    def snapshot(self) -> list[ModuleHealth]:
        now = monotonic()
        with self._lock:
            values = list(self._modules.values())
        result: list[ModuleHealth] = []
        for health in values:
            if (
                health.state not in {HealthState.IDLE, HealthState.FAULT, HealthState.UNKNOWN}
                and health.age_seconds(now) > self.stale_after_seconds
            ):
                result.append(
                    replace(
                        health,
                        state=HealthState.DEGRADED,
                        reason_code="HEARTBEAT_STALE",
                        recommendation="Check the upstream module and recent telemetry events.",
                    )
                )
            else:
                result.append(health)
        return sorted(result, key=lambda item: item.component)
