"""Qt in-process adapter for the high-level Edge ControlPort."""

from __future__ import annotations

from PySide6.QtCore import Q_ARG, QMetaObject, Qt

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

    def _invoke_value(self, method: str, value_type, value) -> None:
        if not QMetaObject.invokeMethod(
            self.controller,
            method,
            Qt.ConnectionType.BlockingQueuedConnection,
            Q_ARG(value_type, value),
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
        mapped = {
            "ai_tracking": "AI Tracking",
            "fixed_cut": "Fixed Cut",
            "in_out_auto": "In/Out Auto",
        }.get(mode)
        if mapped is None:
            raise ValueError(f"unsupported tracking mode: {mode}")
        self._invoke_value("set_track_shot_mode", str, mapped)

    def select_target(self, target_gid: int) -> None:
        self._invoke_value("find_vehicle", int, target_gid)

    def find_target(self, target_gid: int) -> None:
        self._invoke_value("find_vehicle", int, target_gid)

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
        mode = controller.dependencies.track_shot_controller.mode
        mode_wire = {
            "AI Tracking": "ai_tracking",
            "Fixed Cut": "fixed_cut",
            "In/Out Auto": "in_out_auto",
        }.get(mode, "ai_tracking")
        frame_data = controller.last_frame_data
        latency = (
            frame_data.latency_breakdown.end_to_end_ms
            if frame_data is not None and frame_data.latency_breakdown is not None
            else controller.last_inference_ms
        )
        vehicles = controller.application.identity_store.summary(
            feature_counts=controller.application.feature_gallery.summary_by_vehicle()
        ).vehicles
        available_targets = [
            CurrentTarget(
                gid=vehicle.vehicle_id,
                display_name=vehicle.display_name,
                confidence=None,
                tracking_state=(
                    "tracking" if vehicle.vehicle_id == selected_gid else "available"
                ),
            )
            for vehicle in vehicles
        ]
        return Heartbeat(
            app_version=RELEASE_LABEL,
            online=True,
            iphone_connected=server.client_count > 0,
            dockkit_ready=server.motor_ready,
            tracking_running=bool(controller.running),
            tracking_mode=mode_wire,
            current_target=target,
            available_targets=available_targets,
            fps=max(0.0, float(controller._display_fps)),
            latency_ms=max(0.0, float(latency)),
            last_error=(
                server.motor_status.last_error
                if server.motor_status is not None
                else None
            ),
            simulated=False,
        )
