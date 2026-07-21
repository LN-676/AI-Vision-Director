"""Tracking backend boundary for native Ultralytics trackers and Deep OC-SORT."""

from __future__ import annotations

from pathlib import Path
import tempfile
from time import time
from typing import Any, Iterable, Protocol, runtime_checkable

from autocamtracker.tracking.tracker_adapter import DeepOcSortAdapter, TrackerInputDetection
from autocamtracker.vision.detector_backend import DetectorBackend, MODEL_DIR
from autocamtracker.vision.types import InputConfig, TrackedDetection


CACHE_ROOT = Path(tempfile.gettempdir()) / "autocamtracker-cache"
TRACKER_CONFIGS = {
    "bytetrack": "bytetrack.yaml",
    "botsort": "botsort.yaml",
    "deepocsort": "deepocsort.yaml",
}
VEHICLE_CLASS_NAMES = {"car", "truck", "bus", "motorcycle"}


@runtime_checkable
class TrackerBackend(Protocol):
    """Assigns local track IDs to detector observations."""

    @property
    def config_path(self) -> Path | None: ...

    @property
    def adapter(self) -> DeepOcSortAdapter | None: ...

    def initialize(self) -> None: ...

    def configure(self, source_fps: float | None) -> None: ...

    def track(self, frame: Any, frame_index: int) -> list[TrackedDetection]: ...

    def reset(self) -> None: ...


class TrackingResultParser:
    """Maps native backend output without changing v1.77 filtering semantics."""

    def __init__(self, config: InputConfig) -> None:
        self.config = config

    def parse_tracked(
        self,
        results: Iterable[Any],
        frame_index: int,
    ) -> list[TrackedDetection]:
        parsed: list[TrackedDetection] = []
        timestamp = time()
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            xyxy = self.to_list(getattr(boxes, "xyxy", []))
            cls_values = self.to_list(getattr(boxes, "cls", []))
            conf_values = self.to_list(getattr(boxes, "conf", []))
            id_values = self.to_list(getattr(boxes, "id", []))
            for index, bbox_values in enumerate(xyxy):
                class_id = int(cls_values[index]) if index < len(cls_values) else -1
                class_name = str(names.get(class_id, class_id))
                confidence = float(conf_values[index]) if index < len(conf_values) else 0.0
                if self.config.vehicle_classes_only and class_name not in VEHICLE_CLASS_NAMES:
                    continue
                if confidence < self.config.confidence_threshold:
                    continue
                x1, y1, x2, y2 = [float(value) for value in bbox_values]
                track_id = int(id_values[index]) if index < len(id_values) else None
                parsed.append(
                    TrackedDetection(
                        track_id=track_id,
                        bbox=(x1, y1, x2, y2),
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence,
                        center=((x1 + x2) / 2.0, (y1 + y2) / 2.0),
                        frame_index=frame_index,
                        timestamp=timestamp,
                        tracker_name=self.config.tracker_name,
                    )
                )
        return parsed

    def parse_predictions(self, results: Iterable[Any]) -> list[TrackerInputDetection]:
        parsed: list[TrackerInputDetection] = []
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            xyxy = self.to_list(getattr(boxes, "xyxy", []))
            cls_values = self.to_list(getattr(boxes, "cls", []))
            conf_values = self.to_list(getattr(boxes, "conf", []))
            for index, bbox_values in enumerate(xyxy):
                class_id = int(cls_values[index]) if index < len(cls_values) else -1
                class_name = str(names.get(class_id, class_id))
                confidence = float(conf_values[index]) if index < len(conf_values) else 0.0
                if self.config.vehicle_classes_only and class_name not in VEHICLE_CLASS_NAMES:
                    continue
                if confidence < self.config.confidence_threshold:
                    continue
                x1, y1, x2, y2 = [float(value) for value in bbox_values]
                parsed.append(
                    TrackerInputDetection(
                        bbox=(x1, y1, x2, y2),
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence,
                    )
                )
        return parsed

    @staticmethod
    def to_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            value = value.numpy()
        if hasattr(value, "tolist"):
            return value.tolist()
        return list(value)


class UltralyticsTrackerBackend:
    """ByteTrack/BoT-SORT using the same Ultralytics ``model.track`` path."""

    def __init__(self, config: InputConfig, detector: DetectorBackend) -> None:
        self.config = config
        self.detector = detector
        self.parser = TrackingResultParser(config)
        self._config_path: Path | None = None

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def adapter(self) -> None:
        return None

    def initialize(self) -> None:
        pass

    def configure(self, source_fps: float | None) -> None:
        buffer_frames = tracker_buffer_frames(self.config, source_fps)
        if self.config.tracker_name == "botsort":
            self._config_path = self.write_botsort_config(self.config, buffer_frames)
        elif self.config.tracker_name == "bytetrack":
            self._config_path = self.write_bytetrack_config(buffer_frames)
        else:
            self._config_path = None

    def track(self, frame: Any, frame_index: int) -> list[TrackedDetection]:
        tracker_config = str(self._config_path or TRACKER_CONFIGS[self.config.tracker_name])
        results = self.detector.track_with_native_backend(frame, tracker_config)
        return self.parser.parse_tracked(results, frame_index)

    def reset(self) -> None:
        self.detector.reset_native_trackers()

    @staticmethod
    def write_botsort_config(config: InputConfig, track_buffer: int) -> Path:
        config_dir = CACHE_ROOT / "trackers"
        config_dir.mkdir(parents=True, exist_ok=True)
        reid_enabled = bool(config.tracker_reid_enabled)
        reid_suffix = "reid" if reid_enabled else "motion"
        path = config_dir / f"botsort_{reid_suffix}_buffer_{track_buffer}.yaml"
        path.write_text(
            "\n".join(
                [
                    "tracker_type: botsort",
                    "track_high_thresh: 0.25",
                    "track_low_thresh: 0.1",
                    "new_track_thresh: 0.25",
                    f"track_buffer: {track_buffer}",
                    "match_thresh: 0.8",
                    "fuse_score: True",
                    "gmc_method: sparseOptFlow",
                    "proximity_thresh: 0.5",
                    "appearance_thresh: 0.8",
                    f"with_reid: {str(reid_enabled)}",
                    f"model: {(MODEL_DIR / 'yolo26s-reid.onnx').as_posix()}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def write_bytetrack_config(track_buffer: int) -> Path:
        config_dir = CACHE_ROOT / "trackers"
        config_dir.mkdir(parents=True, exist_ok=True)
        path = config_dir / f"bytetrack_buffer_{track_buffer}.yaml"
        path.write_text(
            "\n".join(
                [
                    "tracker_type: bytetrack",
                    "track_high_thresh: 0.25",
                    "track_low_thresh: 0.1",
                    "new_track_thresh: 0.25",
                    f"track_buffer: {track_buffer}",
                    "match_thresh: 0.8",
                    "fuse_score: True",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path


class DeepOcSortTrackerBackend:
    """Deep OC-SORT using the same v1.77 predict → adapter update path."""

    def __init__(self, config: InputConfig, detector: DetectorBackend) -> None:
        self.config = config
        self.detector = detector
        self.parser = TrackingResultParser(config)
        self._adapter: DeepOcSortAdapter | None = None
        self._source_fps: float | None = None

    @property
    def config_path(self) -> None:
        return None

    @property
    def adapter(self) -> DeepOcSortAdapter | None:
        return self._adapter

    def initialize(self) -> None:
        self._adapter = DeepOcSortAdapter(
            model_dir=MODEL_DIR,
            det_thresh=self.config.confidence_threshold,
            max_age=tracker_buffer_frames(self.config, self._source_fps),
            iou_threshold=0.3,
        )

    def configure(self, source_fps: float | None) -> None:
        self._source_fps = source_fps
        if self._adapter is not None:
            self._adapter.max_age = tracker_buffer_frames(self.config, source_fps)
            self._adapter.reset()

    def track(self, frame: Any, frame_index: int) -> list[TrackedDetection]:
        if self._adapter is None:
            raise RuntimeError("Deep OC-SORT tracker is not initialized")
        raw_detections = self.parser.parse_predictions(self.detector.detect(frame))
        tracked = self._adapter.update(raw_detections)
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
                frame_index=frame_index,
                timestamp=timestamp,
                tracker_name=self.config.tracker_name,
            )
            for detection in tracked
        ]

    def reset(self) -> None:
        if self._adapter is not None:
            self._adapter.reset()
        self.detector.reset_native_trackers()


def tracker_buffer_frames(config: InputConfig, source_fps: float | None) -> int:
    fps = source_fps if source_fps and source_fps > 1.0 else 30.0
    return max(1, int(round(float(config.tracker_buffer_seconds) * fps)))


def create_tracker_backend(config: InputConfig, detector: DetectorBackend) -> TrackerBackend:
    if config.tracker_name == "deepocsort":
        return DeepOcSortTrackerBackend(config, detector)
    return UltralyticsTrackerBackend(config, detector)
