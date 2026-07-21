"""UI-independent background worker for detector and pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import time
from typing import Any, Callable, TypeVar

from autocamtracker.core.timestamps import (
    FrameTimeline,
    TimestampStage,
    timestamp_now,
)


T = TypeVar("T")


@dataclass
class TrackingWorkerResult:
    frame_data: Any | None
    raw_frame: Any | None
    inference_time_ms: float
    error: Exception | None = None


class TrackingWorker:
    """Runs detector and pipeline processing away from the delivery thread."""

    def __init__(
        self,
        detector,
        pipeline,
        draw_callback: Callable,
        get_skipped_frames: Callable[[], int],
        should_render_preview: Callable[[], bool] | None = None,
        get_frame_timing: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.detector = detector
        self.pipeline = pipeline
        self.draw_callback = draw_callback
        self.get_skipped_frames = get_skipped_frames
        self.should_render_preview = should_render_preview or (lambda: True)
        self.get_frame_timing = get_frame_timing or (lambda: {})
        self._request_event = Event()
        self._stop_event = Event()
        self._busy = Event()
        self._operation_lock = Lock()
        self._results: Queue[TrackingWorkerResult] = Queue(maxsize=1)
        self._thread = Thread(target=self._run, name="autocam-tracking", daemon=True)
        self._thread.start()

    @property
    def is_busy(self) -> bool:
        return self._busy.is_set() or self._request_event.is_set()

    def request_frame(self) -> bool:
        if self._stop_event.is_set() or self.is_busy:
            return False
        self._request_event.set()
        return True

    def poll(self) -> TrackingWorkerResult | None:
        try:
            return self._results.get_nowait()
        except Empty:
            return None

    def discard_results(self) -> None:
        while True:
            try:
                self._results.get_nowait()
            except Empty:
                return

    def run_locked(self, callback: Callable[[], T]) -> T:
        """Serialize occasional seek/skip/reset operations with inference."""
        with self._operation_lock:
            return callback()

    def close(self) -> None:
        self._stop_event.set()
        self._request_event.set()
        self._thread.join(timeout=10.0)
        self.discard_results()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._request_event.wait(timeout=0.1):
                continue
            self._request_event.clear()
            if self._stop_event.is_set():
                return

            self._busy.set()
            started_at = time()
            try:
                with self._operation_lock:
                    frame, detections, frame_timing, timeline, inference_time_ms = (
                        self._read_track_with_timestamps()
                    )

                if frame is not None:
                    skipped_frames = self.get_skipped_frames()
                    source_fps = self.detector.get_source_fps()

                    frame_data = self.pipeline.process(
                        frame=frame,
                        detections=detections,
                        draw_detections=self.draw_callback,
                        reset_tracker_state=self.detector.reset_tracker_state,
                        inference_time_ms=inference_time_ms,
                        source_fps=source_fps,
                        skipped_frames=skipped_frames,
                        render_preview=self.should_render_preview(),
                        decode_time_ms=float(frame_timing.get("decode_time_ms") or 0.0),
                        receive_latency_ms=frame_timing.get("receive_latency_ms"),
                        timestamps=timeline,
                    )
                else:
                    frame_data = None

                result = TrackingWorkerResult(
                    frame_data=frame_data,
                    raw_frame=frame,
                    inference_time_ms=inference_time_ms,
                )
            except Exception as exc:
                result = TrackingWorkerResult(
                    frame_data=None,
                    raw_frame=None,
                    inference_time_ms=(time() - started_at) * 1000.0,
                    error=exc,
                )
            finally:
                self._busy.clear()
            self._put_latest(result)

    def _read_track_with_timestamps(
        self,
    ) -> tuple[Any | None, list[Any], dict[str, Any], FrameTimeline, float]:
        capture_started = timestamp_now()
        source_id = str(
            getattr(getattr(self.detector, "config", None), "source_type", "unknown")
        )
        read_frame = getattr(self.detector, "read_frame", None)
        track_frame = getattr(self.detector, "track_frame", None)
        if callable(read_frame) and callable(track_frame):
            frame = read_frame()
            capture_completed = timestamp_now()
            frame_timing = self.get_frame_timing() if frame is not None else {}
            timeline = frame_timing.get("timeline")
            if not isinstance(timeline, FrameTimeline):
                timeline = FrameTimeline.local(
                    self._current_frame_id(), source_id, capture_started
                )
                timeline.mark(TimestampStage.CAPTURE_COMPLETED, capture_completed)
            else:
                timeline.mark(TimestampStage.FRAME_DEQUEUED, capture_completed)
            inference_started = timestamp_now()
            timeline.mark(TimestampStage.INFERENCE_STARTED, inference_started)
            detections = track_frame(frame) if frame is not None else []
            inference_completed = timestamp_now()
            timeline.mark(TimestampStage.INFERENCE_COMPLETED, inference_completed)
            inference_time_ms = max(
                0.0,
                inference_completed.monotonic_time_ms
                - inference_started.monotonic_time_ms,
            )
            return frame, detections, frame_timing, timeline, inference_time_ms

        # Compatibility path for injected detectors that expose only the legacy
        # combined API. The full production detector uses the split path above.
        timeline = FrameTimeline.local(self._current_frame_id(), source_id, capture_started)
        timeline.mark(TimestampStage.CAPTURE_COMPLETED, capture_started)
        timeline.mark(TimestampStage.INFERENCE_STARTED, capture_started)
        frame, detections = self.detector.read_and_track()
        inference_completed = timestamp_now()
        timeline.mark(TimestampStage.INFERENCE_COMPLETED, inference_completed)
        frame_timing = self.get_frame_timing() if frame is not None else {}
        supplied = frame_timing.get("timeline")
        if isinstance(supplied, FrameTimeline):
            timeline = supplied
            timeline.mark(TimestampStage.FRAME_DEQUEUED, inference_completed)
            timeline.mark(TimestampStage.INFERENCE_STARTED, capture_started)
            timeline.mark(TimestampStage.INFERENCE_COMPLETED, inference_completed)
        inference_time_ms = max(
            0.0,
            inference_completed.monotonic_time_ms - capture_started.monotonic_time_ms,
        )
        return frame, detections, frame_timing, timeline, inference_time_ms

    def _current_frame_id(self) -> int:
        getter = getattr(self.detector, "get_current_frame_index", None)
        return max(0, int(getter() if callable(getter) else 0))

    def _put_latest(self, result: TrackingWorkerResult) -> None:
        try:
            self._results.put_nowait(result)
            return
        except Full:
            pass
        try:
            self._results.get_nowait()
        except Empty:
            pass
        self._results.put_nowait(result)
