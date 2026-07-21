"""Application service that owns the live detector/pipeline session lifecycle."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from autocamtracker.core.pipeline_processor import PipelineProcessor
from autocamtracker.core.pipeline_worker import TrackingWorker, TrackingWorkerResult
from autocamtracker.vision.detector import InputConfig, VideoDetector


class TrackingSession:
    """Runs tracking use cases without depending on a UI framework."""

    def __init__(
        self,
        pipeline: PipelineProcessor,
        detector_factory: Callable[..., Any] = VideoDetector,
        worker_factory: Callable[..., Any] = TrackingWorker,
    ) -> None:
        self.pipeline = pipeline
        self.detector_factory = detector_factory
        self.worker_factory = worker_factory
        self._detector: Any | None = None
        self._worker: Any | None = None
        self._active_signature: tuple[object, ...] | None = None

    @property
    def has_source(self) -> bool:
        return self._detector is not None

    @property
    def has_worker(self) -> bool:
        return self._worker is not None

    @property
    def source_type(self) -> str | None:
        return self._detector.config.source_type if self._detector is not None else None

    def can_resume(self, config: InputConfig) -> bool:
        return self.has_source and self._active_signature == self.input_signature(config)

    def start(
        self,
        config: InputConfig,
        *,
        frame_provider: Callable[[], Any | None] | None,
        draw_detections: Callable,
        get_skipped_frames: Callable[[], int],
        should_render_preview: Callable[[], bool],
        get_frame_timing: Callable[[], dict[str, Any]],
    ) -> bool:
        """Start or resume a source and return whether it was resumed."""

        resumed = self.can_resume(config)
        self._close_worker()
        if not resumed:
            self.close_source()
            detector = self.detector_factory(replace(config), frame_provider=frame_provider)
            try:
                detector.load_model()
                detector.open_source()
            except Exception:
                detector.close()
                raise
            self._detector = detector
            self._active_signature = self.input_signature(config)

        self._worker = self.worker_factory(
            self._require_detector(),
            self.pipeline,
            draw_detections,
            get_skipped_frames,
            should_render_preview,
            get_frame_timing,
        )
        self._worker.discard_results()
        return resumed

    def pause(self) -> None:
        # The idle worker is retained so pause remains immediate; start() closes
        # and replaces it before resuming, preventing duplicate worker threads.
        pass

    def stop(self) -> None:
        self.close_source()
        self._active_signature = None

    def close_source(self) -> None:
        self._close_worker()
        if self._detector is None:
            return
        clear_temp_cache = self._detector.config.source_type in {"video_file", "video_url"}
        self._detector.close(clear_temp_cache=clear_temp_cache)
        self._detector = None

    def request_frame(self) -> bool:
        return bool(self._worker is not None and self._worker.request_frame())

    def poll(self) -> TrackingWorkerResult | None:
        return self._worker.poll() if self._worker is not None else None

    def discard_results(self) -> None:
        if self._worker is not None:
            self._worker.discard_results()

    def process_next_frame(
        self,
        *,
        draw_detections: Callable,
        inference_time_ms: float,
        skipped_frames: int,
    ) -> tuple[Any | None, Any | None]:
        detector = self._require_detector()

        def process():
            frame, detections = detector.read_and_track()
            if frame is None:
                return None, None
            frame_data = self.pipeline.process(
                frame=frame,
                detections=detections,
                draw_detections=draw_detections,
                reset_tracker_state=detector.reset_tracker_state,
                inference_time_ms=inference_time_ms,
                source_fps=detector.get_source_fps(),
                skipped_frames=skipped_frames,
                render_preview=True,
            )
            return frame, frame_data

        return self._run_locked(process)

    def seek(self, frame_index: int) -> bool:
        detector = self._require_detector()
        return bool(self._run_locked(lambda: detector.seek_video_frame(frame_index)))

    def skip(self, frame_count: int) -> int:
        detector = self._require_detector()
        return int(self._run_locked(lambda: detector.skip_video_frames(frame_count)))

    def reset_pipeline(self) -> None:
        self.pipeline.reset()

    def set_framing_mode(self, mode: str) -> None:
        self.pipeline.reframer.set_framing_mode(mode)

    def set_output_size(self, width: int, height: int) -> None:
        self.pipeline.reframer.config.output_width = width
        self.pipeline.reframer.config.output_height = height

    def get_source_fps(self) -> float | None:
        return self._detector.get_source_fps() if self._detector is not None else None

    def get_source_frame_count(self) -> int | None:
        return self._detector.get_source_frame_count() if self._detector is not None else None

    def get_current_frame_index(self) -> int:
        return self._detector.get_current_frame_index() if self._detector is not None else 0

    def _run_locked(self, callback: Callable[[], Any]) -> Any:
        if self._worker is not None:
            return self._worker.run_locked(callback)
        return callback()

    def _close_worker(self) -> None:
        if self._worker is not None:
            self._worker.close()
            self._worker = None

    def _require_detector(self) -> Any:
        if self._detector is None:
            raise RuntimeError("tracking source is not open")
        return self._detector

    @staticmethod
    def input_signature(config: InputConfig) -> tuple[object, ...]:
        return (
            config.source_type,
            config.camera_index,
            config.video_path,
            config.video_url,
            config.screen_region,
            config.model_path,
            config.tracker_name,
            config.confidence_threshold,
            config.iou_threshold,
            config.vehicle_classes_only,
        )
