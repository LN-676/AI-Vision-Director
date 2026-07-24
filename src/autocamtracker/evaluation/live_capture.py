"""Record live iPhone/closed-loop runs for later ground-truth annotation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any


class LiveBenchmarkRecorder:
    """Writes source video and frame observations without treating predictions as truth."""

    def __init__(self, output_root: Path | str) -> None:
        self.output_root = Path(output_root)
        self.session_dir: Path | None = None
        self._observations = None
        self._video_writer = None
        self._lock = Lock()
        self.frame_count = 0

    @property
    def active(self) -> bool:
        return self._observations is not None

    def start(self, *, source: str, model_path: str, tracker: str) -> Path:
        if self.active:
            raise RuntimeError("A live benchmark recording is already active")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_dir = self.output_root / f"live-{stamp}"
        self.session_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema_version": 1,
            "created_at": stamp,
            "source": source,
            "model_path": model_path,
            "tracker": tracker,
            "ground_truth_status": "pending",
            "notes": (
                "observations.jsonl contains model output only. Add ground_truth "
                "annotations before using this session for accuracy scoring."
            ),
        }
        (self.session_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        self._observations = (self.session_dir / "observations.jsonl").open(
            "w", encoding="utf-8"
        )
        self.frame_count = 0
        return self.session_dir

    def record(self, raw_frame: Any, frame_data: Any) -> None:
        if not self.active or self.session_dir is None:
            return
        with self._lock:
            self._ensure_video_writer(raw_frame, frame_data)
            if self._video_writer is not None:
                self._video_writer.write(raw_frame)
            timeline = getattr(frame_data, "timestamps", None)
            capture_ms = getattr(timeline, "capture_timestamp_ms", None)
            if capture_ms is None:
                capture_ms = self.frame_count * 1000.0 / max(
                    1.0, float(getattr(frame_data, "source_fps", None) or 30.0)
                )
            record = {
                "frame_index": self.frame_count,
                "capture_timestamp_ms": capture_ms,
                "ground_truth": [],
                "output": {
                    "detections": [
                        {
                            "bbox": list(item.bbox),
                            "class_id": item.class_id,
                            "confidence": item.confidence,
                            "track_id": item.track_id,
                        }
                        for item in getattr(frame_data, "detections", ())
                    ],
                    "gid": {
                        "expected_identity_id": (
                            frame_data.selected_global_vehicle_id
                            if frame_data.selected_global_vehicle_id is not None
                            else -1
                        ),
                        "assigned_identity_id": frame_data.selected_global_vehicle_id,
                        "target_visible": bool(frame_data.selected_targets),
                        "motor_safe": bool(frame_data.motor_safe_to_track),
                    },
                },
                "metadata": {
                    "ground_truth_pending": True,
                    "selected_local_track_id": frame_data.selected_local_track_id,
                    "tracking_status": frame_data.tracking_status,
                    "inference_time_ms": frame_data.inference_time_ms,
                    "pipeline_time_ms": frame_data.pipeline_time_ms,
                    "stream_counters": frame_data.stream_counters,
                },
            }
            assert self._observations is not None
            self._observations.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._observations.flush()
            self.frame_count += 1

    def stop(self) -> Path | None:
        with self._lock:
            session = self.session_dir
            if self._video_writer is not None:
                self._video_writer.release()
                self._video_writer = None
            if self._observations is not None:
                self._observations.close()
                self._observations = None
            self.session_dir = None
            return session

    def _ensure_video_writer(self, frame: Any, frame_data: Any) -> None:
        if self._video_writer is not None or self.session_dir is None:
            return
        try:
            import cv2

            height, width = frame.shape[:2]
            fps = max(1.0, float(getattr(frame_data, "source_fps", None) or 30.0))
            writer = cv2.VideoWriter(
                str(self.session_dir / "source.mp4"),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps,
                (int(width), int(height)),
            )
            self._video_writer = writer if writer.isOpened() else None
        except (AttributeError, TypeError, ValueError):
            self._video_writer = None
