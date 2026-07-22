"""Performance evaluation helpers for detector and tracker quality.

The desktop UI can compute live runtime metrics immediately. Dataset metrics
such as precision, recall, and mAP still require labelled evaluation counts or
AP samples, so this module keeps those calculations explicit and testable.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from statistics import fmean
from time import monotonic, time

from autocamtracker.core.frame_data import FrameData


@dataclass(frozen=True)
class ConfusionMatrixStats:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0

    @property
    def precision(self) -> float | None:
        return _safe_divide(self.true_positive, self.true_positive + self.false_positive)

    @property
    def recall(self) -> float | None:
        return _safe_divide(self.true_positive, self.true_positive + self.false_negative)

    @property
    def accuracy(self) -> float | None:
        total = self.true_positive + self.false_positive + self.false_negative + self.true_negative
        return _safe_divide(self.true_positive + self.true_negative, total)


@dataclass(frozen=True)
class RuntimePerformanceSnapshot:
    frame_count: int
    average_fps: float | None
    latest_fps: float | None
    source_fps: float | None
    average_inference_ms: float | None
    latest_inference_ms: float | None
    average_pipeline_ms: float | None
    latest_pipeline_ms: float | None
    average_confidence: float | None
    latest_confidence: float | None
    tracking_stability: float | None
    id_switches: int
    locked_frames: int
    lost_frames: int
    detection_count: int
    candidate_count: int
    skipped_frames: int
    tracking_status: str
    selected_local_track_id: int | None
    selected_global_vehicle_id: int | None
    session_frame_count: int = 0
    processed_fps: float | None = None
    inference_p50_ms: float | None = None
    inference_p95_ms: float | None = None
    inference_p99_ms: float | None = None
    pipeline_p95_ms: float | None = None
    end_to_end_p95_ms: float | None = None
    total_dropped_frames: int = 0
    dropped_frame_rate: float | None = None
    current_loss_seconds: float = 0.0
    completed_loss_episodes: int = 0
    longest_loss_seconds: float = 0.0
    source_frame_id: int | None = None
    stream_counters: dict[str, int] | None = None
    frame_stall_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class LossEpisode:
    start_timestamp_ms: float
    end_timestamp_ms: float | None
    start_frame_id: int | None
    end_frame_id: int | None
    duration_ms: float
    reason_code: str
    global_vehicle_id: int | None
    local_track_id: int | None


class PerformanceEvaluationTracker:
    """Collects a rolling window of frame-level metrics for the UI."""

    def __init__(self, window_size: int = 300) -> None:
        self.window_size = max(1, int(window_size))
        self._fps_values: deque[float] = deque(maxlen=self.window_size)
        self._inference_ms_values: deque[float] = deque(maxlen=self.window_size)
        self._pipeline_ms_values: deque[float] = deque(maxlen=self.window_size)
        self._confidence_values: deque[float] = deque(maxlen=self.window_size)
        self._locked_values: deque[bool] = deque(maxlen=self.window_size)
        self._frame_times_ms: deque[float] = deque(maxlen=self.window_size)
        self._end_to_end_ms_values: deque[float] = deque(maxlen=self.window_size)
        self._last_selected_local_track_id: int | None = None
        self._id_switches = 0
        self._session_frame_count = 0
        self._target_has_been_selected = False
        self._active_loss: LossEpisode | None = None
        self._loss_episodes: deque[LossEpisode] = deque(maxlen=200)
        self._last_recorded_monotonic: float | None = None
        self._latest: RuntimePerformanceSnapshot | None = None

    def reset(self) -> None:
        self._fps_values.clear()
        self._inference_ms_values.clear()
        self._pipeline_ms_values.clear()
        self._confidence_values.clear()
        self._locked_values.clear()
        self._frame_times_ms.clear()
        self._end_to_end_ms_values.clear()
        self._last_selected_local_track_id = None
        self._id_switches = 0
        self._session_frame_count = 0
        self._target_has_been_selected = False
        self._active_loss = None
        self._loss_episodes.clear()
        self._last_recorded_monotonic = None
        self._latest = None

    def record_frame(self, frame_data: FrameData) -> RuntimePerformanceSnapshot:
        fps = _positive_or_none(frame_data.display_fps)
        inference_ms = _positive_or_none(frame_data.inference_time_ms)
        pipeline_ms = _positive_or_none(frame_data.pipeline_time_ms)
        selected_target = frame_data.selected_targets[0] if frame_data.selected_targets else None
        confidence = _positive_or_none(selected_target.confidence if selected_target is not None else None)
        target_locked = bool(
            frame_data.tracking_status == "tracking"
            and selected_target is not None
            and (
                (selected_target.lost_frame_count == 0 and selected_target.status == "tracking")
                or (selected_target.status == "coasting" and selected_target.lost_frame_count <= 3)
            )
        )
        frame_time_ms = _frame_timestamp_ms(frame_data)
        self._last_recorded_monotonic = monotonic()
        self._session_frame_count += 1
        self._frame_times_ms.append(frame_time_ms)
        if frame_data.latency_breakdown is not None:
            self._end_to_end_ms_values.append(frame_data.latency_breakdown.end_to_end_ms)

        if fps is not None:
            self._fps_values.append(fps)
        if inference_ms is not None:
            self._inference_ms_values.append(inference_ms)
        if pipeline_ms is not None:
            self._pipeline_ms_values.append(pipeline_ms)
        if confidence is not None:
            self._confidence_values.append(confidence)
        self._locked_values.append(target_locked)

        selected_lid = frame_data.selected_local_track_id
        selected_gid = frame_data.selected_global_vehicle_id
        if selected_lid is not None or selected_gid is not None:
            self._target_has_been_selected = True
        if (
            selected_lid is not None
            and self._last_selected_local_track_id is not None
            and selected_lid != self._last_selected_local_track_id
        ):
            self._id_switches += 1
        if selected_lid is not None:
            self._last_selected_local_track_id = selected_lid

        self._update_loss_episode(
            frame_data,
            target_locked=target_locked,
            timestamp_ms=frame_time_ms,
        )

        locked_frames = sum(1 for locked in self._locked_values if locked)
        frame_count = len(self._locked_values)
        stream_counters = dict(frame_data.stream_counters)
        upstream_dropped = max(
            int(stream_counters.get("source_sequence_gaps", 0)),
            int(stream_counters.get("iphone_send_dropped", 0)),
        )
        total_dropped = (
            int(frame_data.skipped_frames)
            + upstream_dropped
            + int(stream_counters.get("receive_overwritten", 0))
            + int(stream_counters.get("decode_failed", 0))
        )
        total_expected = self._session_frame_count + total_dropped
        current_loss_ms = self._active_loss.duration_ms if self._active_loss is not None else 0.0
        completed_durations = [episode.duration_ms for episode in self._loss_episodes]
        self._latest = RuntimePerformanceSnapshot(
            frame_count=frame_count,
            average_fps=_mean(self._fps_values),
            latest_fps=fps,
            source_fps=frame_data.source_fps,
            average_inference_ms=_mean(self._inference_ms_values),
            latest_inference_ms=inference_ms,
            average_pipeline_ms=_mean(self._pipeline_ms_values),
            latest_pipeline_ms=pipeline_ms,
            average_confidence=_mean(self._confidence_values),
            latest_confidence=confidence,
            tracking_stability=_safe_divide(locked_frames, frame_count),
            id_switches=self._id_switches,
            locked_frames=locked_frames,
            lost_frames=max(0, frame_count - locked_frames),
            detection_count=len(frame_data.detections),
            candidate_count=len(frame_data.candidates),
            skipped_frames=frame_data.skipped_frames,
            tracking_status=frame_data.tracking_status,
            selected_local_track_id=selected_lid,
            selected_global_vehicle_id=selected_gid,
            session_frame_count=self._session_frame_count,
            processed_fps=_rate(self._frame_times_ms),
            inference_p50_ms=_percentile(self._inference_ms_values, 0.50),
            inference_p95_ms=_percentile(self._inference_ms_values, 0.95),
            inference_p99_ms=_percentile(self._inference_ms_values, 0.99),
            pipeline_p95_ms=_percentile(self._pipeline_ms_values, 0.95),
            end_to_end_p95_ms=_percentile(self._end_to_end_ms_values, 0.95),
            total_dropped_frames=total_dropped,
            dropped_frame_rate=_safe_divide(total_dropped, total_expected),
            current_loss_seconds=current_loss_ms / 1000.0,
            completed_loss_episodes=len(self._loss_episodes),
            longest_loss_seconds=max(completed_durations + [current_loss_ms], default=0.0) / 1000.0,
            source_frame_id=frame_data.source_frame_id,
            stream_counters=stream_counters,
        )
        return self._latest

    def loss_episodes(self) -> list[LossEpisode]:
        episodes = list(self._loss_episodes)
        if self._active_loss is not None:
            episodes.append(self._active_loss)
        return episodes

    def _update_loss_episode(
        self,
        frame_data: FrameData,
        *,
        target_locked: bool,
        timestamp_ms: float,
    ) -> None:
        if not self._target_has_been_selected:
            return
        if target_locked:
            if self._active_loss is not None:
                active = self._active_loss
                self._loss_episodes.append(
                    LossEpisode(
                        start_timestamp_ms=active.start_timestamp_ms,
                        end_timestamp_ms=timestamp_ms,
                        start_frame_id=active.start_frame_id,
                        end_frame_id=frame_data.source_frame_id,
                        duration_ms=max(0.0, timestamp_ms - active.start_timestamp_ms),
                        reason_code=active.reason_code,
                        global_vehicle_id=active.global_vehicle_id,
                        local_track_id=active.local_track_id,
                    )
                )
                self._active_loss = None
            return
        reason = "NO_DETECTION" if not frame_data.detections else "TRACK_NOT_LOCKED"
        if frame_data.camera_cut_detected:
            reason = "SCENE_CUT"
        if self._active_loss is None:
            self._active_loss = LossEpisode(
                start_timestamp_ms=timestamp_ms,
                end_timestamp_ms=None,
                start_frame_id=frame_data.source_frame_id,
                end_frame_id=frame_data.source_frame_id,
                duration_ms=0.0,
                reason_code=reason,
                global_vehicle_id=frame_data.selected_global_vehicle_id,
                local_track_id=frame_data.selected_local_track_id,
            )
        else:
            self._active_loss = replace_loss_duration(
                self._active_loss,
                timestamp_ms,
                frame_data.source_frame_id,
            )

    def snapshot(self) -> RuntimePerformanceSnapshot:
        if self._latest is not None:
            stall_seconds = (
                max(0.0, monotonic() - self._last_recorded_monotonic)
                if self._last_recorded_monotonic is not None
                else 0.0
            )
            if self._active_loss is not None:
                current_seconds = max(
                    self._latest.current_loss_seconds,
                    (time() * 1000.0 - self._active_loss.start_timestamp_ms) / 1000.0,
                )
                return replace(
                    self._latest,
                    current_loss_seconds=current_seconds,
                    longest_loss_seconds=max(
                        self._latest.longest_loss_seconds,
                        current_seconds,
                    ),
                    frame_stall_seconds=stall_seconds,
                )
            return replace(self._latest, frame_stall_seconds=stall_seconds)
        return RuntimePerformanceSnapshot(
            frame_count=0,
            average_fps=None,
            latest_fps=None,
            source_fps=None,
            average_inference_ms=None,
            latest_inference_ms=None,
            average_pipeline_ms=None,
            latest_pipeline_ms=None,
            average_confidence=None,
            latest_confidence=None,
            tracking_stability=None,
            id_switches=0,
            locked_frames=0,
            lost_frames=0,
            detection_count=0,
            candidate_count=0,
            skipped_frames=0,
            tracking_status="idle",
            selected_local_track_id=None,
            selected_global_vehicle_id=None,
            stream_counters={},
        )


def mean_average_precision(ap_values: list[float]) -> float | None:
    cleaned = [max(0.0, min(1.0, value)) for value in ap_values]
    if not cleaned:
        return None
    return fmean(cleaned)


def _safe_divide(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _mean(values: deque[float]) -> float | None:
    if not values:
        return None
    return fmean(values)


def _percentile(values: deque[float], quantile: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _rate(timestamps_ms: deque[float]) -> float | None:
    if len(timestamps_ms) < 2:
        return None
    duration_ms = timestamps_ms[-1] - timestamps_ms[0]
    return (len(timestamps_ms) - 1) * 1000.0 / duration_ms if duration_ms > 0.0 else None


def _frame_timestamp_ms(frame_data: FrameData) -> float:
    if frame_data.timestamps is not None:
        completed = frame_data.timestamps.get("pipeline_completed")
        if completed is not None:
            return completed.wall_time_ms
        if frame_data.timestamps.capture_timestamp_ms is not None:
            return frame_data.timestamps.capture_timestamp_ms
    return time() * 1000.0


def replace_loss_duration(
    episode: LossEpisode,
    timestamp_ms: float,
    frame_id: int | None,
) -> LossEpisode:
    return LossEpisode(
        start_timestamp_ms=episode.start_timestamp_ms,
        end_timestamp_ms=None,
        start_frame_id=episode.start_frame_id,
        end_frame_id=frame_id,
        duration_ms=max(0.0, timestamp_ms - episode.start_timestamp_ms),
        reason_code=episode.reason_code,
        global_vehicle_id=episode.global_vehicle_id,
        local_track_id=episode.local_track_id,
    )


def _positive_or_none(value: float | int | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if value <= 0.0:
        return None
    return value
