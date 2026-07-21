"""Injected application container for tracking and identity use cases."""

from __future__ import annotations

from autocamtracker.application.tracking_session import TrackingSession
from autocamtracker.tracking.auto_feature_sampler import AutoFeatureSampler
from autocamtracker.tracking.detection_store import DetectionStore
from autocamtracker.tracking.feature_gallery import FeatureGallery
from autocamtracker.tracking.identity_manager import GlobalIdentityManager
from autocamtracker.tracking.vehicle_identity_store import VehicleIdentityStore
from autocamtracker.core.pipeline_processor import PipelineProcessor
from autocamtracker.vision.reframer import Reframer
from autocamtracker.vision.scene_cut import SceneCutDetector
from autocamtracker.vision.types import InputConfig
from autocamtracker.vision.camera_calibration import CameraCalibrationSubsystem
from autocamtracker.vision.gmc import GlobalMotionCompensator
from autocamtracker.core.timestamps import LatencyCompensator


class TrackingApplication:
    """Exposes injected CV services to delivery-layer use cases."""

    def __init__(
        self,
        *,
        input_config: InputConfig,
        store: DetectionStore,
        identity_store: VehicleIdentityStore,
        feature_gallery: FeatureGallery,
        identity_manager: GlobalIdentityManager,
        auto_feature_sampler: AutoFeatureSampler,
        scene_cut_detector: SceneCutDetector,
        reframer: Reframer,
        camera_calibration: CameraCalibrationSubsystem,
        gmc: GlobalMotionCompensator,
        latency_compensator: LatencyCompensator,
        pipeline: PipelineProcessor,
        tracking_session: TrackingSession,
    ) -> None:
        self.input_config = input_config
        self.store = store
        self.identity_store = identity_store
        self.feature_gallery = feature_gallery
        self.identity_manager = identity_manager
        self.auto_feature_sampler = auto_feature_sampler
        self.scene_cut_detector = scene_cut_detector
        self.reframer = reframer
        self.camera_calibration = camera_calibration
        self.gmc = gmc
        self.latency_compensator = latency_compensator
        self.pipeline = pipeline
        self.tracking_session = tracking_session

    def close(self) -> None:
        self.tracking_session.stop()
        self.feature_gallery.close()
        self.identity_store.close()
