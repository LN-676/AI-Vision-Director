"""End-to-end frame timestamps and latency compensation contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from time import monotonic, time
from typing import Any, Callable


TIMESTAMP_SCHEMA_VERSION = 1


class TimestampStage(str, Enum):
    CAPTURE_STARTED = "capture_started"
    CAPTURE_COMPLETED = "capture_completed"
    RECEIVED = "received"
    DECODE_STARTED = "decode_started"
    DECODE_COMPLETED = "decode_completed"
    FRAME_DEQUEUED = "frame_dequeued"
    INFERENCE_STARTED = "inference_started"
    INFERENCE_COMPLETED = "inference_completed"
    PIPELINE_STARTED = "pipeline_started"
    PIPELINE_COMPLETED = "pipeline_completed"


class LatencyReasonCode(str, Enum):
    COMPLETE = "COMPLETE"
    LOCAL_SOURCE = "LOCAL_SOURCE"
    CAPTURE_TIMESTAMP_MISSING = "CAPTURE_TIMESTAMP_MISSING"
    CLOCK_SKEW_REJECTED = "CLOCK_SKEW_REJECTED"
    COMPENSATION_CLAMPED = "COMPENSATION_CLAMPED"


@dataclass(frozen=True, slots=True)
class TimestampMark:
    wall_time_ms: float
    monotonic_time_ms: float

    def __post_init__(self) -> None:
        if not isfinite(self.wall_time_ms) or not isfinite(self.monotonic_time_ms):
            raise ValueError("timestamp marks must be finite")

    def to_dict(self) -> dict[str, float]:
        return {
            "wall_time_ms": self.wall_time_ms,
            "monotonic_time_ms": self.monotonic_time_ms,
        }


def timestamp_now(
    wall_clock: Callable[[], float] = time,
    monotonic_clock: Callable[[], float] = monotonic,
) -> TimestampMark:
    return TimestampMark(wall_clock() * 1000.0, monotonic_clock() * 1000.0)


@dataclass(frozen=True, slots=True)
class LatencyBreakdown:
    transport_ms: float | None
    capture_ms: float
    decode_ms: float
    inference_queue_ms: float
    inference_ms: float
    pipeline_queue_ms: float
    pipeline_ms: float
    publish_queue_ms: float
    end_to_end_ms: float
    reason_code: LatencyReasonCode

    def to_dict(self) -> dict[str, Any]:
        return {
            "transport_ms": self.transport_ms,
            "capture_ms": self.capture_ms,
            "decode_ms": self.decode_ms,
            "inference_queue_ms": self.inference_queue_ms,
            "inference_ms": self.inference_ms,
            "pipeline_queue_ms": self.pipeline_queue_ms,
            "pipeline_ms": self.pipeline_ms,
            "publish_queue_ms": self.publish_queue_ms,
            "end_to_end_ms": self.end_to_end_ms,
            "reason_code": self.reason_code.value,
        }


@dataclass(frozen=True, slots=True)
class LatencyCompensation:
    raw_latency_ms: float
    applied_latency_ms: float
    frames_ahead: float
    clamped: bool
    reason_code: LatencyReasonCode

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_latency_ms": self.raw_latency_ms,
            "applied_latency_ms": self.applied_latency_ms,
            "frames_ahead": self.frames_ahead,
            "clamped": self.clamped,
            "reason_code": self.reason_code.value,
        }


@dataclass(slots=True)
class FrameTimeline:
    """One frame's source timestamp plus ordered local clock milestones."""

    frame_id: int
    source_id: str
    capture_timestamp_ms: float | None = None
    capture_clock: str = "source_wall"
    marks: dict[str, TimestampMark] = field(default_factory=dict)
    max_transport_latency_ms: float = 5_000.0

    def __post_init__(self) -> None:
        if self.frame_id < 0:
            raise ValueError("frame_id must be non-negative")
        if not self.source_id:
            raise ValueError("source_id is required")
        if self.capture_timestamp_ms is not None and not isfinite(
            self.capture_timestamp_ms
        ):
            raise ValueError("capture_timestamp_ms must be finite")
        if self.max_transport_latency_ms <= 0.0:
            raise ValueError("max_transport_latency_ms must be positive")

    @classmethod
    def local(
        cls,
        frame_id: int,
        source_id: str,
        capture_started: TimestampMark,
    ) -> "FrameTimeline":
        timeline = cls(
            frame_id=frame_id,
            source_id=source_id,
            capture_timestamp_ms=capture_started.wall_time_ms,
            capture_clock="local_wall",
        )
        timeline.mark(TimestampStage.CAPTURE_STARTED, capture_started)
        return timeline

    def mark(
        self,
        stage: TimestampStage | str,
        value: TimestampMark | None = None,
    ) -> TimestampMark:
        key = stage.value if isinstance(stage, TimestampStage) else str(stage)
        mark = value or timestamp_now()
        previous = self.marks.get(key)
        if previous is not None and mark.monotonic_time_ms < previous.monotonic_time_ms:
            raise ValueError(f"timestamp stage {key} cannot move backwards")
        self.marks[key] = mark
        return mark

    def get(self, stage: TimestampStage | str) -> TimestampMark | None:
        key = stage.value if isinstance(stage, TimestampStage) else str(stage)
        return self.marks.get(key)

    def latency_breakdown(
        self,
        *,
        evaluated_at: TimestampMark | None = None,
    ) -> LatencyBreakdown:
        evaluated = evaluated_at or timestamp_now()
        capture_started = self.get(TimestampStage.CAPTURE_STARTED)
        capture_completed = self.get(TimestampStage.CAPTURE_COMPLETED)
        received = self.get(TimestampStage.RECEIVED)
        decode_started = self.get(TimestampStage.DECODE_STARTED)
        decode_completed = self.get(TimestampStage.DECODE_COMPLETED)
        dequeued = self.get(TimestampStage.FRAME_DEQUEUED)
        inference_started = self.get(TimestampStage.INFERENCE_STARTED)
        inference_completed = self.get(TimestampStage.INFERENCE_COMPLETED)
        pipeline_started = self.get(TimestampStage.PIPELINE_STARTED)
        pipeline_completed = self.get(TimestampStage.PIPELINE_COMPLETED)

        transport_ms, reason = self._transport_latency(received)
        capture_ms = _duration(capture_started, capture_completed)
        decode_ms = _duration(decode_started, decode_completed)
        inference_anchor = decode_completed or dequeued or received or capture_completed
        inference_queue_ms = _duration(inference_anchor, inference_started)
        inference_ms = _duration(inference_started, inference_completed)
        pipeline_queue_ms = _duration(inference_completed, pipeline_started)
        pipeline_ms = _duration(pipeline_started, pipeline_completed)
        publish_queue_ms = _duration(pipeline_completed, evaluated)

        local_origin = received or capture_started or capture_completed or dequeued
        local_elapsed_ms = _duration(local_origin, evaluated)
        if received is not None and transport_ms is not None:
            end_to_end_ms = transport_ms + local_elapsed_ms
        else:
            end_to_end_ms = local_elapsed_ms
        return LatencyBreakdown(
            transport_ms=transport_ms,
            capture_ms=capture_ms,
            decode_ms=decode_ms,
            inference_queue_ms=inference_queue_ms,
            inference_ms=inference_ms,
            pipeline_queue_ms=pipeline_queue_ms,
            pipeline_ms=pipeline_ms,
            publish_queue_ms=publish_queue_ms,
            end_to_end_ms=max(0.0, end_to_end_ms),
            reason_code=reason,
        )

    def _transport_latency(
        self, received: TimestampMark | None
    ) -> tuple[float | None, LatencyReasonCode]:
        if self.capture_clock == "local_wall":
            return None, LatencyReasonCode.LOCAL_SOURCE
        if self.capture_timestamp_ms is None or received is None:
            return None, LatencyReasonCode.CAPTURE_TIMESTAMP_MISSING
        latency = received.wall_time_ms - self.capture_timestamp_ms
        if latency < 0.0 or latency > self.max_transport_latency_ms:
            return None, LatencyReasonCode.CLOCK_SKEW_REJECTED
        return latency, LatencyReasonCode.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TIMESTAMP_SCHEMA_VERSION,
            "frame_id": self.frame_id,
            "source_id": self.source_id,
            "capture_timestamp_ms": self.capture_timestamp_ms,
            "capture_clock": self.capture_clock,
            "marks": {
                name: mark.to_dict()
                for name, mark in sorted(self.marks.items())
            },
        }


class LatencyCompensator:
    def __init__(
        self,
        *,
        max_latency_ms: float = 500.0,
        max_prediction_frames: float = 5.0,
    ) -> None:
        if max_latency_ms <= 0.0 or max_prediction_frames <= 0.0:
            raise ValueError("latency compensation limits must be positive")
        self.max_latency_ms = max_latency_ms
        self.max_prediction_frames = max_prediction_frames

    def evaluate(
        self,
        timeline: FrameTimeline,
        source_fps: float | None,
        *,
        evaluated_at: TimestampMark | None = None,
    ) -> tuple[LatencyBreakdown, LatencyCompensation]:
        return evaluate_latency_compensation(
            timeline,
            source_fps,
            evaluated_at=evaluated_at,
            max_latency_ms=self.max_latency_ms,
            max_prediction_frames=self.max_prediction_frames,
        )


def evaluate_latency_compensation(
    timeline: FrameTimeline,
    source_fps: float | None,
    *,
    evaluated_at: TimestampMark | None = None,
    max_latency_ms: float = 500.0,
    max_prediction_frames: float = 5.0,
) -> tuple[LatencyBreakdown, LatencyCompensation]:
    breakdown = timeline.latency_breakdown(evaluated_at=evaluated_at)
    fps = max(1.0, float(source_fps or 30.0))
    frame_duration_ms = 1000.0 / fps
    limit_ms = min(max_latency_ms, max_prediction_frames * frame_duration_ms)
    applied = min(breakdown.end_to_end_ms, limit_ms)
    clamped = applied < breakdown.end_to_end_ms
    reason = (
        LatencyReasonCode.COMPENSATION_CLAMPED
        if clamped else breakdown.reason_code
    )
    return breakdown, LatencyCompensation(
        raw_latency_ms=breakdown.end_to_end_ms,
        applied_latency_ms=applied,
        frames_ahead=applied / frame_duration_ms,
        clamped=clamped,
        reason_code=reason,
    )


def _duration(start: TimestampMark | None, end: TimestampMark | None) -> float:
    if start is None or end is None:
        return 0.0
    return max(0.0, end.monotonic_time_ms - start.monotonic_time_ms)
