"""The single composition root for the AI Vision Director desktop process."""

from __future__ import annotations

from dataclasses import dataclass
from queue import SimpleQueue
import sys
import tkinter as tk
from typing import Any, Callable, Sequence

from autocamtracker.application import TrackingApplication
from autocamtracker.application.tracking_session import TrackingSession
from autocamtracker.core.desktop_state import IdentitySessionLinks
from autocamtracker.core.pipeline_processor import PipelineProcessor
from autocamtracker.core.performance_evaluation import PerformanceEvaluationTracker
from autocamtracker.core.telemetry_logger import TelemetryLogger
from autocamtracker.core.diagnostics import DiagnosticsService, HealthState
from autocamtracker.core.track_shot_plan import TrackShotController
from autocamtracker.server.websocket_server import TrackingWebSocketServer
from autocamtracker.server.camera_control_policy import CameraControlPolicy
from autocamtracker.tracking.auto_feature_sampler import AutoFeatureSampler
from autocamtracker.tracking.detection_store import DetectionStore
from autocamtracker.tracking.feature_gallery import FeatureGallery
from autocamtracker.tracking.identity_components import (
    IdentityMatcher,
    IdentityStateMachine,
    MotorSafetyPolicy,
    ReacquisitionPolicy,
    TrackIdentityMapper,
)
from autocamtracker.tracking.identity_manager import GlobalIdentityManager
from autocamtracker.tracking.vehicle_identity_store import VehicleIdentityStore
from autocamtracker.ui.app import AIVisonDirectorApp, AppConfig, AppDependencies
from autocamtracker.vision.reframer import FramingConfig, Reframer
from autocamtracker.vision.framing_engine import FramingEngine, FramingEngineConfig
from autocamtracker.vision.scene_cut import SceneCutDetector
from autocamtracker.vision.types import InputConfig
from autocamtracker.vision.camera_calibration import (
    CameraCalibrationStore,
    CameraCalibrationSubsystem,
)
from autocamtracker.vision.gmc import GlobalMotionCompensator
from autocamtracker.core.timestamps import LatencyCompensator


@dataclass(frozen=True)
class BootstrappedDesktop:
    """The process objects needed to enter the Tk event loop."""

    root: Any
    app: AIVisonDirectorApp

    def run(self) -> None:
        self.root.mainloop()


def bootstrap(
    *,
    config: AppConfig | None = None,
    argv: Sequence[str] | None = None,
    root_factory: Callable[[], Any] = tk.Tk,
    app_factory: Callable[..., AIVisonDirectorApp] = AIVisonDirectorApp,
) -> BootstrappedDesktop:
    """Construct the complete desktop object graph exactly once."""

    app_config = config or AppConfig()
    status_queue: SimpleQueue[str] = SimpleQueue()
    control_queue: SimpleQueue[dict] = SimpleQueue()
    telemetry_logger = TelemetryLogger(app_config.telemetry_dir)
    diagnostics_service = DiagnosticsService()
    input_config = InputConfig()
    store = DetectionStore()
    identity_store = VehicleIdentityStore(app_config.identity_db_path)
    feature_gallery = FeatureGallery(
        app_config.identity_db_path,
        reid_model_path=str(app_config.model_dir / app_config.default_reid_model),
    )
    diagnostics_service.update(
        "database",
        HealthState.HEALTHY,
        "SQLite identity store initialized",
        metrics={"path": str(app_config.identity_db_path)},
    )
    diagnostics_service.update(
        "feature_gallery",
        HealthState.HEALTHY,
        "feature repository initialized",
        metrics={"model": app_config.default_reid_model},
    )
    identity_manager = GlobalIdentityManager(
        identity_store=identity_store,
        feature_gallery=feature_gallery,
        state_machine=IdentityStateMachine(),
        identity_matcher=IdentityMatcher(),
        reacquisition_policy=ReacquisitionPolicy(),
        track_identity_mapper=TrackIdentityMapper(),
        motor_safety_policy=MotorSafetyPolicy(),
    )
    auto_feature_sampler = AutoFeatureSampler(
        feature_gallery, identity_manager=identity_manager
    )
    scene_cut_detector = SceneCutDetector()
    camera_calibration = CameraCalibrationSubsystem(
        CameraCalibrationStore(app_config.camera_calibration_path)
    )
    gmc = GlobalMotionCompensator(calibration=camera_calibration)
    latency_compensator = LatencyCompensator()
    camera_control_policy = CameraControlPolicy()
    framing_config = FramingConfig(
        output_width=app_config.output_width,
        output_height=app_config.output_height,
    )
    framing_engine = FramingEngine(
        FramingEngineConfig(
            center_smoothing=framing_config.smooth_factor,
            movement_dead_zone_ratio=framing_config.dead_zone_ratio,
        )
    )
    reframer = Reframer(framing_config, engine=framing_engine)
    pipeline = PipelineProcessor(
        store=store,
        identity_manager=identity_manager,
        scene_cut_detector=scene_cut_detector,
        reframer=reframer,
        gmc=gmc,
        latency_compensator=latency_compensator,
    )
    tracking_session = TrackingSession(pipeline)
    application = TrackingApplication(
        input_config=input_config,
        store=store,
        identity_store=identity_store,
        feature_gallery=feature_gallery,
        identity_manager=identity_manager,
        auto_feature_sampler=auto_feature_sampler,
        scene_cut_detector=scene_cut_detector,
        reframer=reframer,
        framing_engine=framing_engine,
        camera_calibration=camera_calibration,
        gmc=gmc,
        latency_compensator=latency_compensator,
        camera_control_policy=camera_control_policy,
        pipeline=pipeline,
        tracking_session=tracking_session,
    )
    tracking_server = TrackingWebSocketServer(
        on_status=status_queue.put,
        on_control=control_queue.put,
        telemetry_logger=telemetry_logger,
        latency_compensator=latency_compensator,
        camera_control_policy=camera_control_policy,
    )
    dependencies = AppDependencies(
        application=application,
        telemetry_logger=telemetry_logger,
        performance_evaluator=PerformanceEvaluationTracker(),
        diagnostics_service=diagnostics_service,
        tracking_server=tracking_server,
        track_shot_controller=TrackShotController(),
        identity_session_links=IdentitySessionLinks(),
        iphone_status_queue=status_queue,
        iphone_control_queue=control_queue,
    )
    root = root_factory()
    app = app_factory(root, app_config, dependencies)

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        app.input_config.source_type = "video_file"
        app.input_config.video_path = arguments[0]
    return BootstrappedDesktop(root=root, app=app)


def run(argv: Sequence[str] | None = None) -> None:
    bootstrap(argv=argv).run()
