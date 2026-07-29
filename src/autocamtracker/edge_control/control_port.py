"""High-level Desktop control boundary; raw motor velocity is intentionally absent."""

from __future__ import annotations

from typing import Protocol

from autocamtracker.edge_control.models import Heartbeat


class ControlPort(Protocol):
    def start_tracking(self) -> None: ...
    def stop_tracking(self) -> None: ...
    def home(self) -> None: ...
    def emergency_stop(self) -> None: ...
    def set_tracking_mode(self, mode: str) -> None: ...
    def select_target(self, target_gid: int) -> None: ...
    def find_target(self, target_gid: int) -> None: ...
    def telemetry(self) -> Heartbeat: ...


class UnavailableControlPort:
    """Safe CLI default when the agent is not embedded in the Desktop process."""

    def _unavailable(self) -> None:
        raise RuntimeError(
            "Desktop bridge unavailable; run the Desktop with Edge Agent environment configured"
        )

    start_tracking = stop_tracking = home = emergency_stop = _unavailable

    def set_tracking_mode(self, mode: str) -> None:
        self._unavailable()

    def select_target(self, target_gid: int) -> None:
        self._unavailable()

    def find_target(self, target_gid: int) -> None:
        self._unavailable()

    def telemetry(self) -> Heartbeat:
        from autocamtracker.product import RELEASE_LABEL

        return Heartbeat(
            app_version=RELEASE_LABEL,
            online=True,
            iphone_connected=False,
            dockkit_ready=False,
            tracking_running=False,
            last_error="Desktop bridge unavailable",
        )


class SimulatedControlPort:
    """Explicitly labeled demo fallback; it never claims real hardware state."""

    def __init__(self) -> None:
        self.running = False
        self.mode = "ai_tracking"
        self.target_gid: int | None = None

    def start_tracking(self) -> None:
        self.running = True

    def stop_tracking(self) -> None:
        self.running = False

    def home(self) -> None:
        return None

    def emergency_stop(self) -> None:
        self.running = False

    def set_tracking_mode(self, mode: str) -> None:
        self.mode = mode

    def select_target(self, target_gid: int) -> None:
        self.target_gid = target_gid

    def find_target(self, target_gid: int) -> None:
        self.target_gid = target_gid

    def telemetry(self) -> Heartbeat:
        from autocamtracker.edge_control.models import CurrentTarget
        from autocamtracker.product import RELEASE_LABEL

        target = (
            CurrentTarget(
                gid=self.target_gid,
                display_name=f"Demo GID {self.target_gid}",
                confidence=0.92,
                tracking_state="tracking" if self.running else "selected",
            )
            if self.target_gid is not None
            else None
        )
        return Heartbeat(
            app_version=RELEASE_LABEL,
            online=True,
            iphone_connected=False,
            dockkit_ready=False,
            tracking_running=self.running,
            tracking_mode=self.mode,
            current_target=target,
            available_targets=[] if target is None else [target],
            fps=30.0 if self.running else 0.0,
            latency_ms=42.0 if self.running else None,
            simulated=True,
        )
