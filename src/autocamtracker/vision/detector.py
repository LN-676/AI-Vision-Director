"""Compatibility façade for the split v1.77 vision pipeline.

``VideoDetector`` keeps its established API while delegating frame acquisition,
object detection, and local tracking to independent backend boundaries.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from time import time
from typing import Any, Callable, Iterable

from autocamtracker.tracking.backend import (
    TRACKER_CONFIGS,
    DeepOcSortTrackerBackend,
    TrackerBackend,
    TrackingResultParser,
    UltralyticsTrackerBackend,
    create_tracker_backend,
    tracker_buffer_frames,
)
from autocamtracker.tracking.tracker_adapter import DeepOcSortAdapter, TrackerInputDetection
from autocamtracker.vision.detector_backend import (
    CACHE_ROOT,
    MODEL_DIR,
    PROJECT_ROOT,
    DetectorBackend,
    UltralyticsDetectorBackend,
)
from autocamtracker.vision.frame_source import ConfiguredFrameSource, FrameSource
from autocamtracker.vision.types import (
    InputConfig,
    SourceType,
    TrackedDetection,
    TrackerName,
)


VEHICLE_CLASS_NAMES = {"car", "truck", "bus", "motorcycle"}


class VideoDetector:
    """Backward-compatible coordinator for source, detector, and tracker backends."""

    def __init__(
        self,
        config: InputConfig,
        frame_provider: Callable[[], Any | None] | None = None,
        *,
        frame_source: FrameSource | None = None,
        detector_backend: DetectorBackend | None = None,
        tracker_backend: TrackerBackend | None = None,
    ) -> None:
        self.config = config
        self.frame_provider = frame_provider
        self.frame_source = frame_source or ConfiguredFrameSource(config, frame_provider)
        self.detector_backend = detector_backend or UltralyticsDetectorBackend(config)
        self.tracker_backend = tracker_backend or create_tracker_backend(
            config, self.detector_backend
        )

    def load_model(self) -> None:
        self.detector_backend.load()
        self.tracker_backend.initialize()

    def open_source(self) -> None:
        self.frame_source.open()
        self._configure_tracker_buffer()

    def read_frame(self) -> Any | None:
        return self.frame_source.read()

    def track_frame(self, frame: Any) -> list[TrackedDetection]:
        if self.model is None:
            raise RuntimeError("YOLO model is not loaded")
        return self.tracker_backend.track(frame, self.get_current_frame_index())

    def read_and_track(self) -> tuple[Any | None, list[TrackedDetection]]:
        frame = self.read_frame()
        if frame is None:
            return None, []
        return frame, self.track_frame(frame)

    def close(self, clear_temp_cache: bool = False) -> None:
        self.frame_source.close()
        if clear_temp_cache:
            self.clear_temp_cache()

    @staticmethod
    def clear_temp_cache() -> None:
        if CACHE_ROOT.exists():
            shutil.rmtree(CACHE_ROOT, ignore_errors=True)

    def get_source_fps(self) -> float | None:
        return self.frame_source.get_fps()

    def get_source_frame_count(self) -> int | None:
        return self.frame_source.get_frame_count()

    def get_current_frame_index(self) -> int:
        return self.frame_source.get_frame_index()

    def seek_video_frame(self, frame_index: int) -> bool:
        if self.config.source_type not in {"video_file", "video_url"}:
            return False
        if isinstance(self.frame_source, ConfiguredFrameSource) and (
            self.frame_source.capture is None or self.frame_source._cv2 is None
        ):
            return False
        self.reset_tracker_state()
        return self.frame_source.seek(frame_index)

    def skip_video_frames(self, frame_count: int) -> int:
        return self.frame_source.skip(frame_count)

    def reset_tracker_state(self) -> None:
        self.tracker_backend.reset()

    def _configure_tracker_buffer(self) -> None:
        self.tracker_backend.configure(self.get_source_fps())

    def _tracker_buffer_frames(self) -> int:
        return tracker_buffer_frames(self.config, self.get_source_fps())

    # Compatibility properties keep existing UI/tests decoupled from this phase.
    @property
    def model(self) -> Any | None:
        return self.detector_backend.model

    @model.setter
    def model(self, value: Any | None) -> None:
        if hasattr(self.detector_backend, "_model"):
            setattr(self.detector_backend, "_model", value)
        else:
            setattr(self.detector_backend, "model", value)

    @property
    def tracker_adapter(self) -> DeepOcSortAdapter | None:
        return getattr(self, "_tracker_adapter_override", self.tracker_backend.adapter)

    @tracker_adapter.setter
    def tracker_adapter(self, value: DeepOcSortAdapter | None) -> None:
        if hasattr(self.tracker_backend, "_adapter"):
            setattr(self.tracker_backend, "_adapter", value)
        else:
            self._tracker_adapter_override = value

    @property
    def capture(self) -> Any | None:
        return getattr(self.frame_source, "capture", None)

    @capture.setter
    def capture(self, value: Any | None) -> None:
        setattr(self.frame_source, "capture", value)

    @property
    def screen_capture(self) -> Any | None:
        return getattr(self.frame_source, "screen_capture", None)

    @screen_capture.setter
    def screen_capture(self, value: Any | None) -> None:
        setattr(self.frame_source, "screen_capture", value)

    @property
    def source_fps(self) -> float | None:
        return self.get_source_fps()

    @source_fps.setter
    def source_fps(self, value: float | None) -> None:
        setattr(self.frame_source, "source_fps", value)

    @property
    def source_frame_count(self) -> int | None:
        return self.get_source_frame_count()

    @source_frame_count.setter
    def source_frame_count(self, value: int | None) -> None:
        setattr(self.frame_source, "source_frame_count", value)

    @property
    def frame_index(self) -> int:
        return self.get_current_frame_index()

    @frame_index.setter
    def frame_index(self, value: int) -> None:
        setattr(self.frame_source, "frame_index", value)

    @property
    def _cv2(self) -> Any | None:
        return getattr(self.frame_source, "_cv2", None)

    @_cv2.setter
    def _cv2(self, value: Any | None) -> None:
        setattr(self.frame_source, "_cv2", value)

    @property
    def _tracker_config_path(self) -> Path | None:
        return self.tracker_backend.config_path

    @_tracker_config_path.setter
    def _tracker_config_path(self, value: Path | None) -> None:
        if hasattr(self.tracker_backend, "_config_path"):
            setattr(self.tracker_backend, "_config_path", value)
        else:
            setattr(self.tracker_backend, "config_path", value)

    def _write_botsort_config(self, track_buffer: int) -> Path:
        return UltralyticsTrackerBackend.write_botsort_config(self.config, track_buffer)

    @staticmethod
    def _write_bytetrack_config(track_buffer: int) -> Path:
        return UltralyticsTrackerBackend.write_bytetrack_config(track_buffer)

    def _parse_results(self, results: Iterable[Any]) -> list[TrackedDetection]:
        return TrackingResultParser(self.config).parse_tracked(results, self.frame_index)

    def _parse_prediction_results(self, results: Iterable[Any]) -> list[TrackerInputDetection]:
        return TrackingResultParser(self.config).parse_predictions(results)

    def _track_with_deepocsort(self, results: Iterable[Any]) -> list[TrackedDetection]:
        adapter = self.tracker_adapter
        if adapter is None:
            raise RuntimeError("Deep OC-SORT tracker is not initialized")
        tracked = adapter.update(self._parse_prediction_results(results))
        timestamp = time()
        return [
            TrackedDetection(
                track_id=detection.track_id,
                bbox=detection.bbox,
                class_id=detection.class_id,
                class_name=detection.class_name,
                confidence=detection.confidence,
                center=(
                    (detection.bbox[0] + detection.bbox[2]) / 2.0,
                    (detection.bbox[1] + detection.bbox[3]) / 2.0,
                ),
                frame_index=self.frame_index,
                timestamp=timestamp,
                tracker_name=self.config.tracker_name,
            )
            for detection in tracked
        ]

    @staticmethod
    def _to_list(value: Any) -> list[Any]:
        return TrackingResultParser.to_list(value)

    @staticmethod
    def _resolve_model_path(model_path: str) -> Path:
        return UltralyticsDetectorBackend.resolve_model_path(model_path)

    @staticmethod
    def _resolve_input_path(input_path: str) -> Path:
        return ConfiguredFrameSource.resolve_input_path(input_path)

    @staticmethod
    def _validate_video_url(video_url: str) -> str:
        return ConfiguredFrameSource.validate_video_url(video_url)

    @classmethod
    def _resolve_video_url(cls, video_url: str) -> str:
        return ConfiguredFrameSource.resolve_video_url(video_url)

    @staticmethod
    def _extract_stream_url(video_url: str) -> str:
        return ConfiguredFrameSource.extract_stream_url(video_url)

    @staticmethod
    def _camera_error_message(camera_index: int) -> str:
        return ConfiguredFrameSource._camera_error_message(camera_index)

    def _open_camera_capture(self, cv2: Any, backend: int) -> Any | None:
        method = getattr(self.frame_source, "_open_camera_capture", None)
        return method(cv2, backend) if callable(method) else None

    def _read_capture_fps(self, cv2: Any, capture: Any | None = None) -> float | None:
        method = getattr(self.frame_source, "_read_capture_fps", None)
        return method(cv2, capture) if callable(method) else None

    @staticmethod
    def _configure_capture(cv2: Any, capture: Any) -> None:
        ConfiguredFrameSource._configure_capture(cv2, capture)

    def _read_capture_frame_count(self, cv2: Any, capture: Any | None = None) -> int | None:
        method = getattr(self.frame_source, "_read_capture_frame_count", None)
        return method(cv2, capture) if callable(method) else None


__all__ = [
    "CACHE_ROOT",
    "DetectorBackend",
    "FrameSource",
    "InputConfig",
    "MODEL_DIR",
    "PROJECT_ROOT",
    "SourceType",
    "TRACKER_CONFIGS",
    "TrackedDetection",
    "TrackerBackend",
    "TrackerName",
    "VideoDetector",
]
