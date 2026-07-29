"""Qt in-process adapter for the high-level Edge ControlPort."""

from __future__ import annotations

from PySide6.QtCore import QMetaObject, Qt

from autocamtracker.edge_control.models import CurrentTarget, Heartbeat
from autocamtracker.product import RELEASE_LABEL


class QtControlPort:
    def __init__(self, controller) -> None:
        self.controller = controller

    def _invoke(self, method: str) -> None:
        if not QMetaObject.invokeMethod(
            self.controller, method, Qt.ConnectionType.BlockingQueuedConnection
        ):
            raise RuntimeError(f"Desktop rejected {method}")

    def start_tracking(self) -> None:
        self._invoke("start")

    def stop_tracking(self) -> None:
        self._invoke("stop")

    def home(self) -> None:
        self._invoke("home")

    def emergency_stop(self) -> None:
        self._invoke("emergency_stop")

    def set_tracking_mode(self, mode: str) -> None:
        raise RuntimeError("tracking mode remote adapter is not enabled in this MVP")

    def select_target(self, target_gid: int) -> None:
        raise RuntimeError("target selection remote adapter is not enabled in this MVP")

    def find_target(self, target_gid: int) -> None:
        raise RuntimeError("find target remote adapter is not enabled in this MVP")

    def telemetry(self) -> Heartbeat:
        controller = self.controller
        server = controller.dependencies.tracking_server
        selected_gid = controller.application.identity_manager.selected_global_vehicle_id
        target = (
            CurrentTarget(
                gid=selected_gid,
                display_name=controller.vehicle_display_name(selected_gid),
                confidence=None,
                tracking_state="tracking" if controller.running else "selected",
            )
            if selected_gid is not None
            else None
        )
        return Heartbeat(
            app_version=RELEASE_LABEL,
            online=True,
            iphone_connected=server.client_count > 0,
            dockkit_ready=server.motor_ready,
            tracking_running=bool(controller.running),
            current_target=target,
            available_targets=[] if target is None else [target],
            fps=max(0.0, float(controller._display_fps)),
            latency_ms=max(0.0, float(controller.last_inference_ms)),
            last_error=(
                server.motor_status.last_error
                if server.motor_status is not None
                else None
            ),
            simulated=False,
        )
