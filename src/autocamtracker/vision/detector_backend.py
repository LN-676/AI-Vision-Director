"""Object-detection backend boundary and the V1.0 Ultralytics implementation."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Protocol, runtime_checkable

from autocamtracker.vision.types import InputConfig


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = PROJECT_ROOT / "code" / "model"
CACHE_ROOT = Path(tempfile.gettempdir()) / "autocamtracker-cache"


@runtime_checkable
class DetectorBackend(Protocol):
    """Loads a detector and returns its native prediction results."""

    @property
    def model(self) -> Any | None: ...

    def load(self) -> None: ...

    def detect(self, frame: Any) -> Iterable[Any]: ...

    def track_with_native_backend(self, frame: Any, tracker_config: str) -> Iterable[Any]: ...

    def reset_native_trackers(self) -> None: ...


class UltralyticsDetectorBackend:
    """Preserves the established YOLO predict/track invocation parameters."""

    def __init__(self, config: InputConfig) -> None:
        self.config = config
        self._model: Any | None = None

    @property
    def model(self) -> Any | None:
        return self._model

    def load(self) -> None:
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        for name in ("ultralytics", "matplotlib", "xdg"):
            (CACHE_ROOT / name).mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("YOLO_CONFIG_DIR", str(CACHE_ROOT / "ultralytics"))
        os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
        os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT / "xdg"))

        from ultralytics import YOLO

        resolved_model_path = self.resolve_model_path(self.config.model_path)
        self.config.model_path = str(resolved_model_path)
        self._model = YOLO(str(resolved_model_path))

    def detect(self, frame: Any) -> Iterable[Any]:
        model = self._require_model()
        return model.predict(
            frame,
            conf=self.config.confidence_threshold,
            iou=self.config.iou_threshold,
            imgsz=self.config.detector_imgsz,
            verbose=False,
        )

    def track_with_native_backend(self, frame: Any, tracker_config: str) -> Iterable[Any]:
        model = self._require_model()
        return model.track(
            frame,
            persist=True,
            tracker=tracker_config,
            conf=self.config.confidence_threshold,
            iou=self.config.iou_threshold,
            imgsz=self.config.detector_imgsz,
            verbose=False,
        )

    def reset_native_trackers(self) -> None:
        trackers = getattr(self._model, "trackers", None)
        if not trackers:
            return
        for tracker in trackers:
            reset = getattr(tracker, "reset", None)
            if callable(reset):
                reset()

    def _require_model(self) -> Any:
        if self._model is None:
            raise RuntimeError("YOLO model is not loaded")
        return self._model

    @staticmethod
    def resolve_model_path(model_path: str) -> Path:
        path = Path(model_path).expanduser()
        candidates: list[Path] = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend([MODEL_DIR / path, PROJECT_ROOT / path, Path.cwd() / path, path])
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        searched = "\n".join(f"- {candidate}" for candidate in candidates)
        raise FileNotFoundError(
            f"YOLO model not found: {model_path}\n"
            "Put the model under code/model and click Refresh Models.\n"
            f"Searched:\n{searched}"
        )
