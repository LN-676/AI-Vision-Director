"""Deterministic offline replay orchestration and report generation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from autocamtracker.evaluation.control import ControlMetrics, evaluate_control
from autocamtracker.evaluation.detection import DetectionMetrics, evaluate_detection
from autocamtracker.evaluation.models import (
    ControlObservation,
    EvaluationObject,
    FrameEvaluation,
    ReIDObservation,
    ReplayFrame,
    ReplayOutput,
)
from autocamtracker.evaluation.reid import ReIDMetrics, evaluate_reid
from autocamtracker.evaluation.system import SystemMetrics, SystemSample, evaluate_system
from autocamtracker.evaluation.tracking import TrackingMetrics, evaluate_tracking


@dataclass(frozen=True)
class OfflineReplayReport:
    frame_count: int
    processed_frame_count: int
    dropped_frame_count: int
    detection: DetectionMetrics
    tracking: TrackingMetrics
    reid: ReIDMetrics
    system: SystemMetrics
    control: ControlMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_count": self.frame_count,
            "processed_frame_count": self.processed_frame_count,
            "dropped_frame_count": self.dropped_frame_count,
            "Detection": {
                "mAP50": self.detection.map50,
                "mAP50-95": self.detection.map50_95,
                "Precision": self.detection.precision,
                "Recall": self.detection.recall,
            },
            "Tracking": {
                "HOTA": self.tracking.hota,
                "IDF1": self.tracking.idf1,
                "MOTA": self.tracking.mota,
                "ID switches": self.tracking.id_switches,
                "Fragmentation": self.tracking.fragmentation,
            },
            "ReID": {
                "Rank-1": self.reid.rank1,
                "Rank-5": self.reid.rank5,
                "mAP": self.reid.mean_average_precision,
                "False Reacquire Rate": self.reid.false_reacquire_rate,
                "Reacquire Success Rate": self.reid.reacquire_success_rate,
            },
            "System": {
                "FPS": self.system.fps,
                "capture-to-command latency p50 ms": self.system.latency_p50_ms,
                "capture-to-command latency p95 ms": self.system.latency_p95_ms,
                "capture-to-command latency p99 ms": self.system.latency_p99_ms,
                "Dropped frame rate": self.system.dropped_frame_rate,
            },
            "Control": {
                "Overshoot": self.control.overshoot,
                "Settling time ms": self.control.settling_time_ms,
                "Jitter": self.control.jitter,
                "Target-out-of-frame ratio": self.control.target_out_of_frame_ratio,
            },
        }


class OfflineReplayRunner:
    """Replay recorded frames without UI, WebSocket, or wall-clock scheduling."""

    def __init__(
        self,
        processor: Callable[[ReplayFrame], ReplayOutput] | None = None,
        *,
        control_settling_tolerance: float = 0.05,
    ) -> None:
        self.processor = processor
        self.control_settling_tolerance = control_settling_tolerance

    def run(self, frames: Iterable[ReplayFrame]) -> OfflineReplayReport:
        ordered = sorted(frames, key=lambda item: item.frame_index)
        if len({frame.frame_index for frame in ordered}) != len(ordered):
            raise ValueError("Replay frame indexes must be unique")
        frame_evaluations = []
        system_samples = []
        reid_observations = []
        control_observations = []
        processed_count = 0
        for frame in ordered:
            output = None
            if not frame.dropped:
                output = self.processor(frame) if self.processor is not None else frame.recorded_output
                if output is None:
                    raise ValueError(
                        f"Replay frame {frame.frame_index} has no processor output or recorded_output"
                    )
                processed_count += 1
            predictions = output.detections if output is not None else ()
            frame_evaluations.append(FrameEvaluation(frame.frame_index, frame.ground_truth, predictions))
            system_samples.append(SystemSample(
                capture_timestamp_ms=frame.capture_timestamp_ms,
                command_timestamp_ms=output.command_timestamp_ms if output is not None else None,
                dropped=frame.dropped,
            ))
            if output is not None and output.reid is not None:
                reid_observations.append(output.reid)
            if output is not None and output.control is not None:
                control_observations.append(output.control)
        return OfflineReplayReport(
            frame_count=len(ordered),
            processed_frame_count=processed_count,
            dropped_frame_count=len(ordered) - processed_count,
            detection=evaluate_detection(frame_evaluations),
            tracking=evaluate_tracking(frame_evaluations),
            reid=evaluate_reid(reid_observations),
            system=evaluate_system(system_samples),
            control=evaluate_control(
                control_observations,
                settling_tolerance=self.control_settling_tolerance,
            ),
        )

    def run_jsonl(self, path: Path | str) -> OfflineReplayReport:
        return self.run(load_replay_jsonl(path))


def load_replay_jsonl(path: Path | str) -> list[ReplayFrame]:
    frames = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            frames.append(_frame_from_mapping(payload))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid replay JSONL record at line {line_number}") from error
    return frames


def _frame_from_mapping(payload: dict[str, Any]) -> ReplayFrame:
    output_payload = payload.get("output")
    output = _output_from_mapping(output_payload) if isinstance(output_payload, dict) else None
    return ReplayFrame(
        frame_index=int(payload["frame_index"]),
        capture_timestamp_ms=float(payload["capture_timestamp_ms"]),
        ground_truth=tuple(_object_from_mapping(item) for item in payload.get("ground_truth", [])),
        payload=payload.get("payload"),
        dropped=bool(payload.get("dropped", False)),
        recorded_output=output,
        metadata=payload.get("metadata", {}),
    )


def _output_from_mapping(payload: dict[str, Any]) -> ReplayOutput:
    reid_payload = payload.get("reid")
    control_payload = payload.get("control")
    reid = None
    if isinstance(reid_payload, dict):
        reid = ReIDObservation(
            expected_identity_id=int(reid_payload["expected_identity_id"]),
            ranked_identity_ids=tuple(int(item) for item in reid_payload.get("ranked_identity_ids", [])),
            reacquire_attempted=bool(reid_payload.get("reacquire_attempted", False)),
            reacquired_identity_id=(
                int(reid_payload["reacquired_identity_id"])
                if reid_payload.get("reacquired_identity_id") is not None else None
            ),
        )
    control = None
    if isinstance(control_payload, dict):
        control = ControlObservation(
            timestamp_ms=float(control_payload["timestamp_ms"]),
            error_x=float(control_payload.get("error_x", 0.0)),
            error_y=float(control_payload.get("error_y", 0.0)),
            command_x=float(control_payload.get("command_x", 0.0)),
            command_y=float(control_payload.get("command_y", 0.0)),
            target_in_frame=bool(control_payload.get("target_in_frame", True)),
        )
    return ReplayOutput(
        detections=tuple(_object_from_mapping(item) for item in payload.get("detections", [])),
        command_timestamp_ms=(
            float(payload["command_timestamp_ms"])
            if payload.get("command_timestamp_ms") is not None else None
        ),
        reid=reid,
        control=control,
    )


def _object_from_mapping(payload: dict[str, Any]) -> EvaluationObject:
    return EvaluationObject(
        bbox=tuple(float(value) for value in payload["bbox"]),  # type: ignore[arg-type]
        class_id=int(payload["class_id"]),
        confidence=float(payload.get("confidence", 1.0)),
        identity_id=int(payload["identity_id"]) if payload.get("identity_id") is not None else None,
        track_id=int(payload["track_id"]) if payload.get("track_id") is not None else None,
    )
