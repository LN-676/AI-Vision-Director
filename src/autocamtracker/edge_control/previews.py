"""Rate-limited publication of local Before/After monitor frames and timing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import monotonic, perf_counter, time
from typing import Any

import cv2


class EdgePreviewPublisher:
    def __init__(
        self,
        directory: Path,
        *,
        interval_seconds: float = 0.1,
        jpeg_quality: int = 72,
        maximum_width: int = 960,
    ) -> None:
        self.directory = directory
        self.interval_seconds = max(0.05, float(interval_seconds))
        self.jpeg_quality = max(40, min(95, int(jpeg_quality)))
        self.maximum_width = max(320, int(maximum_width))
        self._last_published_at = 0.0

    def publish(
        self,
        before,
        after,
        *,
        now: float | None = None,
        timing: dict[str, Any] | None = None,
    ) -> bool:
        observed_at = monotonic() if now is None else float(now)
        if observed_at - self._last_published_at < self.interval_seconds:
            return False
        encoded = {
            "before": self._encode(before),
            "after": self._encode(after),
        }
        published_timestamp_ms = time() * 1000.0
        self.directory.mkdir(parents=True, exist_ok=True)
        for name, (payload, encode_ms, width, height) in encoded.items():
            temporary = self.directory / f".{name}.{os.getpid()}.tmp"
            temporary.write_bytes(payload)
            os.replace(temporary, self.directory / f"{name}.jpg")
            metadata = {
                "schema_version": 1,
                "view": name,
                "published_timestamp_ms": published_timestamp_ms,
                "encode_duration_ms": encode_ms,
                "jpeg_bytes": len(payload),
                "width": width,
                "height": height,
                **(timing or {}),
            }
            metadata_temporary = self.directory / f".{name}.{os.getpid()}.json.tmp"
            metadata_temporary.write_text(
                json.dumps(metadata, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(metadata_temporary, self.directory / f"{name}.json")
        self._last_published_at = observed_at
        return True

    def _encode(self, frame) -> tuple[bytes, float, int, int]:
        height, width = frame.shape[:2]
        if width > self.maximum_width:
            scale = self.maximum_width / float(width)
            frame = cv2.resize(
                frame,
                (self.maximum_width, max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
            height, width = frame.shape[:2]
        started_at = perf_counter()
        ok, payload = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        encode_ms = (perf_counter() - started_at) * 1000.0
        if not ok:
            raise ValueError("unable to encode Edge preview frame")
        return payload.tobytes(), encode_ms, width, height
