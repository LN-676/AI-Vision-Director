"""Structured JSONL telemetry for hardware bring-up sessions."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from collections import deque
import json
from pathlib import Path
from threading import Lock
from time import monotonic, time
from typing import Any
from uuid import uuid4


TELEMETRY_SCHEMA_VERSION = 2


class TelemetryLogger:
    """Append timestamped events that can be correlated across desktop/iPhone."""

    def __init__(self, log_dir: Path, session_name: str | None = None) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = session_name or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = log_dir / f"autocamtracker-telemetry-{stamp}.jsonl"
        self._lock = Lock()
        self.session_id = f"{stamp}-{uuid4().hex[:8]}"
        self._recent: deque[dict[str, Any]] = deque(maxlen=500)

    def log(
        self,
        event: str,
        *,
        severity: str = "info",
        component: str | None = None,
        reason_code: str | None = None,
        **fields: Any,
    ) -> None:
        payload = {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "session_id": self.session_id,
            "event": event,
            "severity": severity.lower(),
            "component": component or _component_for_event(event),
            "reason_code": reason_code,
            "timestamp_ms": int(time() * 1000),
            "monotonic_s": monotonic(),
            **fields,
        }
        safe_payload = _json_safe(payload)
        line = json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._recent.append(safe_payload)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")

    def recent_events(
        self,
        limit: int = 100,
        *,
        minimum_severity: str | None = None,
    ) -> list[dict[str, Any]]:
        requested = max(0, int(limit))
        if requested == 0:
            return []
        ranks = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
        threshold = ranks.get((minimum_severity or "debug").lower(), 10)
        with self._lock:
            matches = [
                dict(item)
                for item in self._recent
                if ranks.get(str(item.get("severity", "info")).lower(), 20) >= threshold
            ]
        return matches[-requested:]


def _component_for_event(event: str) -> str:
    prefix = event.split("_", 1)[0]
    return {
        "app": "desktop",
        "camera": "camera_stream",
        "control": "control",
        "desktop": "desktop",
        "find": "identity",
        "frame": "pipeline",
        "motor": "motor",
        "ws": "websocket",
    }.get(prefix, "application")


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
