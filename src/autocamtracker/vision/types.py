"""Compatibility types shared by the v1.0-alpha.1 vision backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SourceType = Literal["webcam", "video_file", "video_url", "screen_region", "iphone"]
TrackerName = Literal["bytetrack", "botsort", "deepocsort"]


@dataclass
class InputConfig:
    source_type: SourceType = "webcam"
    camera_index: int = 0
    video_path: str | None = None
    video_url: str | None = None
    screen_region: tuple[int, int, int, int] | None = None
    model_path: str = "model/yolo26s.pt"
    tracker_name: TrackerName = "botsort"
    confidence_threshold: float = 0.20
    iou_threshold: float = 0.65
    vehicle_classes_only: bool = True
    tracker_buffer_seconds: float = 5.0
    target_source_fps: float = 30.0
    detector_imgsz: int | None = 640
    tracker_reid_enabled: bool = False


@dataclass
class TrackedDetection:
    track_id: int | None
    bbox: tuple[float, float, float, float]
    class_id: int
    class_name: str
    confidence: float
    center: tuple[float, float]
    frame_index: int
    timestamp: float
    tracker_name: TrackerName
