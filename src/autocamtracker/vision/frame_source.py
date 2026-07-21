"""Frame acquisition boundary for webcam, file, URL, screen, and iPhone input."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.parse import urlparse

from autocamtracker.vision.types import InputConfig


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@runtime_checkable
class FrameSource(Protocol):
    """Produces frames and owns source-specific playback state."""

    def open(self) -> None: ...

    def read(self) -> Any | None: ...

    def close(self) -> None: ...

    def get_fps(self) -> float | None: ...

    def get_frame_count(self) -> int | None: ...

    def get_frame_index(self) -> int: ...

    def seek(self, frame_index: int) -> bool: ...

    def skip(self, frame_count: int) -> int: ...


class ConfiguredFrameSource:
    """The V1.0 source implementation extracted from ``VideoDetector``."""

    def __init__(
        self,
        config: InputConfig,
        frame_provider: Callable[[], Any | None] | None = None,
    ) -> None:
        self.config = config
        self.frame_provider = frame_provider
        self.capture: Any | None = None
        self.screen_capture: Any | None = None
        self.source_fps: float | None = None
        self.source_frame_count: int | None = None
        self.frame_index = 0
        self._cv2: Any | None = None

    def open(self) -> None:
        if self.config.source_type in {"webcam", "video_file", "video_url"}:
            import cv2

            self._cv2 = cv2
            source: int | str
            if self.config.source_type == "webcam":
                backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
                self.capture = self._open_camera_capture(cv2, backend)
                if self.capture is None:
                    raise RuntimeError(self._camera_error_message(self.config.camera_index))
                return
            if self.config.source_type == "video_file":
                if not self.config.video_path:
                    raise ValueError("video_path is required for video_file input")
                source = str(self.resolve_input_path(self.config.video_path))
                backend = cv2.CAP_ANY
            else:
                if not self.config.video_url:
                    raise ValueError("video_url is required for video_url input")
                source = self.resolve_video_url(self.config.video_url)
                backend = cv2.CAP_ANY

            self.capture = cv2.VideoCapture(source, backend)
            if not self.capture.isOpened():
                raise RuntimeError(f"Unable to open video source: {source}")
            self._configure_capture(cv2, self.capture)
            self.source_fps = self._read_capture_fps(cv2)
            self.source_frame_count = self._read_capture_frame_count(cv2)
            return

        if self.config.source_type == "screen_region":
            if self.config.screen_region is None:
                raise ValueError("screen_region is required for screen_region input")
            import mss

            self.screen_capture = mss.mss()
            self.source_fps = None
            self.source_frame_count = None
            return

        if self.config.source_type == "iphone":
            if self.frame_provider is None:
                raise ValueError("frame_provider is required for iphone input")
            self.source_fps = max(1.0, float(self.config.target_source_fps))
            self.source_frame_count = None
            return

        raise ValueError(f"Unsupported source_type: {self.config.source_type}")

    def read(self) -> Any | None:
        if self.config.source_type in {"webcam", "video_file", "video_url"}:
            if self.capture is None:
                raise RuntimeError("Input source is not open")
            ok, frame = self.capture.read()
            if not ok:
                return None
            self.frame_index += 1
            return frame

        if self.config.source_type == "screen_region":
            if self.screen_capture is None:
                raise RuntimeError("Screen capture source is not open")
            import cv2
            import numpy as np

            x, y, width, height = self.config.screen_region or (0, 0, 0, 0)
            image = self.screen_capture.grab(
                {"left": x, "top": y, "width": width, "height": height}
            )
            frame = cv2.cvtColor(np.array(image), cv2.COLOR_BGRA2BGR)
            self.frame_index += 1
            return frame

        if self.config.source_type == "iphone":
            if self.frame_provider is None:
                raise RuntimeError("iPhone frame provider is unavailable")
            frame = self.frame_provider()
            if frame is not None:
                self.frame_index += 1
            return frame

        return None

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
        if self.screen_capture is not None:
            self.screen_capture.close()
        self.capture = None
        self.screen_capture = None
        self.source_fps = None
        self.source_frame_count = None
        self.frame_index = 0

    def get_fps(self) -> float | None:
        return self.source_fps

    def get_frame_count(self) -> int | None:
        return self.source_frame_count

    def get_frame_index(self) -> int:
        return self.frame_index

    def seek(self, frame_index: int) -> bool:
        if (
            self.config.source_type not in {"video_file", "video_url"}
            or self.capture is None
            or self._cv2 is None
        ):
            return False
        target_frame = max(0, int(frame_index))
        if self.source_frame_count is not None:
            target_frame = min(max(0, self.source_frame_count - 1), target_frame)
        ok = self.capture.set(self._cv2.CAP_PROP_POS_FRAMES, target_frame)
        if ok:
            self.frame_index = target_frame
        return bool(ok)

    def skip(self, frame_count: int) -> int:
        if self.config.source_type not in {"video_file", "video_url"} or self.capture is None:
            return 0
        skipped = 0
        for _ in range(max(0, frame_count)):
            if not self.capture.grab():
                break
            self.frame_index += 1
            skipped += 1
        return skipped

    @staticmethod
    def resolve_input_path(input_path: str) -> Path:
        path = Path(input_path).expanduser()
        if path.is_absolute():
            return path
        candidates = [PROJECT_ROOT / path, Path.cwd() / path, path]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return PROJECT_ROOT / path

    @staticmethod
    def validate_video_url(video_url: str) -> str:
        value = video_url.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "rtsp", "rtmp"} or not parsed.netloc:
            raise ValueError("Video URL must start with http://, https://, rtsp://, or rtmp://")
        return value

    @classmethod
    def resolve_video_url(cls, video_url: str) -> str:
        value = cls.validate_video_url(video_url)
        parsed = urlparse(value)
        if parsed.scheme in {"rtsp", "rtmp"}:
            return value
        return cls.extract_stream_url(value)

    @staticmethod
    def extract_stream_url(video_url: str) -> str:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError(
                "Network video URLs require yt-dlp. Install dependencies with "
                "`.venv/bin/python -m pip install -r requirements.txt`."
            ) from exc

        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "format": "best[protocol^=http][vcodec!=none]/best[protocol^=m3u8][vcodec!=none]/best[vcodec!=none]/best",
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(video_url, download=False)
        except Exception as exc:
            raise RuntimeError(f"Unable to resolve video URL: {video_url}") from exc
        if not isinstance(info, dict):
            raise RuntimeError(f"Unable to resolve video URL: {video_url}")
        stream_url = info.get("url")
        if stream_url:
            return str(stream_url)
        for item in reversed(info.get("formats") or []):
            if not isinstance(item, dict):
                continue
            candidate = item.get("url")
            vcodec = item.get("vcodec")
            protocol = str(item.get("protocol") or "")
            if candidate and vcodec != "none" and protocol.startswith(("http", "m3u8")):
                return str(candidate)
        raise RuntimeError(f"No playable video stream found for URL: {video_url}")

    @staticmethod
    def _camera_error_message(camera_index: int) -> str:
        mac_hint = ""
        if sys.platform == "darwin":
            mac_hint = (
                "\n\nmacOS permission fix:\n"
                "1. Open System Settings > Privacy & Security > Camera.\n"
                "2. Enable Camera permission for Visual Studio Code, Terminal, "
                "or the app that launched Python.\n"
                "3. Quit and reopen VSCode/Terminal, then run again."
            )
        return (
            "Unable to open MacBook camera. "
            f"Camera index {camera_index} and fallback indexes 0-4 are not available, blocked by permission, "
            "or currently used by another app."
            f"{mac_hint}"
        )

    def _open_camera_capture(self, cv2: Any, backend: int) -> Any | None:
        indexes = [self.config.camera_index]
        indexes.extend(index for index in range(5) if index != self.config.camera_index)
        for index in indexes:
            capture = cv2.VideoCapture(index, backend)
            if capture.isOpened():
                self.config.camera_index = index
                self._configure_capture(cv2, capture)
                self.source_fps = self._read_capture_fps(cv2, capture)
                return capture
            capture.release()
        return None

    def _read_capture_fps(self, cv2: Any, capture: Any | None = None) -> float | None:
        target = capture or self.capture
        if target is None:
            return None
        fps = float(target.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 1.0 or fps > 240.0:
            return None
        return fps

    @staticmethod
    def _configure_capture(cv2: Any, capture: Any) -> None:
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _read_capture_frame_count(self, cv2: Any, capture: Any | None = None) -> int | None:
        target = capture or self.capture
        if target is None:
            return None
        frame_count = int(target.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        return frame_count if frame_count > 0 else None
