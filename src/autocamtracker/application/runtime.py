"""Application composition root for the tracking and identity use cases."""

from __future__ import annotations

from pathlib import Path

from autocamtracker.application.tracking_session import TrackingSession
from autocamtracker.tracking.auto_feature_sampler import AutoFeatureSampler
from autocamtracker.tracking.detection_store import DetectionStore
from autocamtracker.tracking.feature_gallery import FeatureGallery
from autocamtracker.tracking.identity_manager import GlobalIdentityManager
from autocamtracker.tracking.vehicle_identity_store import VehicleIdentityStore
from autocamtracker.core.pipeline_processor import PipelineProcessor
from autocamtracker.vision.reframer import FramingConfig, Reframer
from autocamtracker.vision.scene_cut import SceneCutDetector
from autocamtracker.vision.types import InputConfig


class TrackingApplication:
    """Owns CV services so delivery layers only coordinate application use cases."""

    def __init__(
        self,
        *,
        identity_db_path: Path,
        reid_model_path: str,
        output_width: int,
        output_height: int,
    ) -> None:
        self.input_config = InputConfig()
        self.store = DetectionStore()
        self.identity_store = VehicleIdentityStore(identity_db_path)
        self.feature_gallery = FeatureGallery(identity_db_path, reid_model_path=reid_model_path)
        self.identity_manager = GlobalIdentityManager(
            identity_store=self.identity_store,
            feature_gallery=self.feature_gallery,
        )
        self.auto_feature_sampler = AutoFeatureSampler(self.feature_gallery)
        self.scene_cut_detector = SceneCutDetector()
        self.reframer = Reframer(
            FramingConfig(output_width=output_width, output_height=output_height)
        )
        self.pipeline = PipelineProcessor(
            store=self.store,
            identity_manager=self.identity_manager,
            scene_cut_detector=self.scene_cut_detector,
            reframer=self.reframer,
        )
        self.tracking_session = TrackingSession(self.pipeline)

    def close(self) -> None:
        self.tracking_session.stop()
        self.feature_gallery.close()
        self.identity_store.close()
