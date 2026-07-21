"""Tkinter UI + Recording + Debug Log module for AI_Vison_Director.

Responsibilities:
- Create the Tkinter desktop UI.
- Invoke application-layer tracking and identity use cases.
- Show before and after views.
- Expose controls for source, tracker, framing mode, and recording.

CV runtime construction and execution live in ``autocamtracker.application``.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from queue import Empty, SimpleQueue
import sys
from threading import Thread
from time import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageGrab, ImageTk
except ImportError:  # pragma: no cover
    Image = None
    ImageGrab = None
    ImageTk = None

from autocamtracker.application import FrameData
from autocamtracker.product import DISPLAY_NAME


@dataclass
class AppConfig:
    window_title: str = DISPLAY_NAME
    update_interval_ms: int = 15
    output_width: int = 640
    output_height: int = 360
    log_dir: Path = Path("outputs")
    telemetry_dir: Path = Path("outputs") / "telemetry"
    identity_db_path: Path = Path("outputs") / "vehicle_identity.sqlite3"
    camera_calibration_path: Path = Path("outputs") / "camera_calibrations.json"
    model_dir: Path = Path(__file__).resolve().parents[3] / "code" / "model"
    default_model: str = "yolo26n.pt"
    default_reid_model: str = "yolo26s-reid.onnx"


@dataclass(frozen=True)
class AppDependencies:
    """Fully constructed services injected by the composition root."""

    application: object
    telemetry_logger: object
    performance_evaluator: object
    tracking_server: object
    track_shot_controller: object
    identity_session_links: object
    iphone_status_queue: SimpleQueue[str]
    iphone_control_queue: SimpleQueue[dict]



from autocamtracker.ui.mixins.ui_builder import UIBuilderMixin
from autocamtracker.ui.mixins.identity_panel import IdentityPanelMixin
from autocamtracker.ui.mixins.video_pipeline import VideoPipelineMixin
from autocamtracker.ui.mixins.commands import CommandsMixin
from autocamtracker.ui.mixins.performance_panel import PerformancePanelMixin

class AIVisonDirectorApp(UIBuilderMixin, IdentityPanelMixin, VideoPipelineMixin, CommandsMixin, PerformancePanelMixin):
    def __init__(self, root: tk.Tk, config: AppConfig, dependencies: AppDependencies) -> None:
        self.root = root
        self.config = config
        self.root.title(self.config.window_title)
        self.root.minsize(1120, 720)

        self.application = dependencies.application
        self.input_config = self.application.input_config
        self.tracking_session = self.application.tracking_session
        # Transitional aliases keep the existing identity-panel interactions
        # stable while CV construction and session execution live outside Tk.
        self.store = self.application.store
        self.identity_store = self.application.identity_store
        self.feature_gallery = self.application.feature_gallery
        self.identity_manager = self.application.identity_manager
        self.auto_feature_sampler = self.application.auto_feature_sampler
        self.scene_cut_detector = self.application.scene_cut_detector
        self.reframer = self.application.reframer
        self.camera_calibration = self.application.camera_calibration
        self.gmc = self.application.gmc
        self.latency_compensator = self.application.latency_compensator
        self.telemetry_logger = dependencies.telemetry_logger
        self.performance_evaluator = dependencies.performance_evaluator
        self.iphone_status_queue = dependencies.iphone_status_queue
        self.iphone_control_queue = dependencies.iphone_control_queue
        self.tracking_server = dependencies.tracking_server
        self.telemetry_logger.log(
            "app_started",
            version=self.config.window_title,
            telemetry_path=self.telemetry_logger.path,
        )
        self.track_shot_controller = dependencies.track_shot_controller
        # Physical motor output is explicitly armed by Auto Track or Find GID.
        # A selected target can therefore still drive digital reframing without
        # unexpectedly moving the DockKit accessory.
        self.iphone_motor_tracking_enabled = False
        self.gid_follow_vehicle_id: int | None = None

        self.running = False
        self.recording = False
        self.last_frame_time = time()
        self.loop_started_at = time()
        self.fps = 0.0
        self.skipped_frames = 0
        self.last_inference_time_ms = 0.0
        self.model_options: dict[str, str] = {}
        self.reid_model_options: dict[str, str] = {}
        self.last_frame_shape: tuple[int, int, int] | tuple[int, int] | None = None
        self.last_raw_frame = None
        self.current_frame_data: FrameData | None = None
        self.display_width = self.config.output_width
        self.display_height = self.config.output_height
        self.preview_width_limit = self.display_width
        self.preview_height_limit = self.display_height
        self.rendered_image_width = self.display_width
        self.rendered_image_height = self.display_height
        self.timeline_dragging = False
        self.refreshing_identity_panel = False
        self.selected_identity_tree_ids: set[int] = set()
        self.identity_session_links = dependencies.identity_session_links
        self.last_identity_panel_refresh_at = 0.0
        self.identity_preview_window: tk.Toplevel | None = None
        self.performance_window: tk.Toplevel | None = None
        self.diagnostics_window: tk.Toplevel | None = None
        self.identity_preview_label: ttk.Label | None = None
        self.identity_preview_photo = None
        self.identity_preview_vehicle_id: int | None = None
        self.identity_manage_button_vehicle_id: int | None = None
        self.auto_feature_status_message = ""
        self.last_desktop_state_publish_at = 0.0
        self.last_frame_telemetry_at = 0.0
        self.last_preview_render_at = 0.0
        self.preview_render_interval_seconds = 0.10

        self.before_image_ref = None
        self.after_image_ref = None
        self._build_ui()
        self.root.after(100, self._drain_iphone_status)
        self.root.after(100, self._drain_iphone_control)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_model_options()
        self.refresh_reid_model_options()
        self.root.after_idle(self.on_source_selected)
        self.root.after_idle(self._preload_reid_model)

    """Tkinter integration shell for the five V1 modules."""


# Backward-compatible import for integrations written before V1.0-alpha.1.
AutoCamTrackerApp = AIVisonDirectorApp
