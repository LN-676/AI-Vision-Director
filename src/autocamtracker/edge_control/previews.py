"""Rate-limited publication of local Before/After monitor frames."""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

import cv2


class EdgePreviewPublisher:
    def __init__(self, directory: Path, *, interval_seconds: float = 0.2) -> None:
        self.directory = directory
        self.interval_seconds = max(0.05, float(interval_seconds))
        self._last_published_at = 0.0

    def publish(self, before, after, *, now: float | None = None) -> bool:
        observed_at = monotonic() if now is None else float(now)
        if observed_at - self._last_published_at < self.interval_seconds:
            return False
        encoded = {"before": self._encode(before), "after": self._encode(after)}
        self.directory.mkdir(parents=True, exist_ok=True)
        for name, payload in encoded.items():
            temporary = self.directory / f".{name}.{os.getpid()}.tmp"
            temporary.write_bytes(payload)
            os.replace(temporary, self.directory / f"{name}.jpg")
        self._last_published_at = observed_at
        return True

    @staticmethod
    def _encode(frame) -> bytes:
        ok, payload = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 82],
        )
        if not ok:
            raise ValueError("unable to encode Edge preview frame")
        return payload.tobytes()
