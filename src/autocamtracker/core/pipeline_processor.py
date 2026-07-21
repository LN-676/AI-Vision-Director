"""Frame pipeline boundary for AI_Vison_Director V1.

The application layer owns scheduling and playback while this class owns the
per-frame data flow from detections to identity, reframing, and FrameData.
"""

from __future__ import annotations

from time import time
from typing import Callable

from autocamtracker.tracking.detection_store import DetectionStore
from autocamtracker.core.frame_data import FrameData
from autocamtracker.tracking.identity_manager import GlobalIdentityManager
from autocamtracker.vision.reframer import Reframer
from autocamtracker.vision.scene_cut import SceneCutDetector
from autocamtracker.vision.detector import TrackedDetection
from autocamtracker.vision.gmc import GlobalMotionCompensator, GMCReasonCode
from autocamtracker.core.timestamps import (
    FrameTimeline,
    LatencyCompensator,
    TimestampMark,
    TimestampStage,
    evaluate_latency_compensation,
    timestamp_now,
)


class PipelineProcessor:
    def __init__(
        self,
        store: DetectionStore,
        identity_manager: GlobalIdentityManager,
        scene_cut_detector: SceneCutDetector,
        reframer: Reframer,
        gmc: GlobalMotionCompensator | None = None,
        latency_compensator: LatencyCompensator | None = None,
    ) -> None:
        self.store = store
        self.identity_manager = identity_manager
        self.scene_cut_detector = scene_cut_detector
        self.reframer = reframer
        self.gmc = gmc
        self.latency_compensator = latency_compensator

    def reset(self) -> None:
        self.store.reset()
        self.identity_manager.reset()
        self.scene_cut_detector.reset()
        self.reframer.reset()
        if self.gmc is not None:
            self.gmc.reset()

    def process(
        self,
        frame,
        detections: list[TrackedDetection],
        draw_detections: Callable[[object, list[TrackedDetection]], object],
        reset_tracker_state: Callable[[], None] | None = None,
        inference_time_ms: float = 0.0,
        source_fps: float | None = None,
        skipped_frames: int = 0,
        render_preview: bool = True,
        decode_time_ms: float = 0.0,
        receive_latency_ms: float | None = None,
        timestamps: FrameTimeline | None = None,
    ) -> FrameData:
        pipeline_started_at = time()
        pipeline_started_mark = timestamp_now()
        if timestamps is None:
            frame_id = max(
                (int(getattr(detection, "frame_index", 0)) for detection in detections),
                default=0,
            )
            inferred_start = TimestampMark(
                pipeline_started_mark.wall_time_ms - max(0.0, inference_time_ms),
                pipeline_started_mark.monotonic_time_ms - max(0.0, inference_time_ms),
            )
            timestamps = FrameTimeline.local(frame_id, "pipeline", inferred_start)
            timestamps.mark(TimestampStage.CAPTURE_COMPLETED, inferred_start)
            timestamps.mark(TimestampStage.INFERENCE_STARTED, inferred_start)
            timestamps.mark(TimestampStage.INFERENCE_COMPLETED, pipeline_started_mark)
        timestamps.mark(TimestampStage.PIPELINE_STARTED, pipeline_started_mark)
        camera_cut = self.scene_cut_detector.update(frame)
        if camera_cut:
            if reset_tracker_state is not None:
                reset_tracker_state()
            self.store.reset()
            self.identity_manager.handle_camera_cut()
            detections = []

        gmc_started_at = time()
        global_motion = None
        if self.gmc is not None:
            if camera_cut:
                self.gmc.reset(GMCReasonCode.CAMERA_CUT_RESET)
            global_motion = self.gmc.update(
                frame, [detection.bbox for detection in detections]
            )
        gmc_time_ms = (time() - gmc_started_at) * 1000.0

        identity_started_at = time()
        candidates = self.store.update(detections, frame.shape)
        selected_targets = self.identity_manager.update(detections, frame)
        identity_time_ms = (time() - identity_started_at) * 1000.0
        target_velocity = (
            self.identity_manager.selected_identity.velocity
            if self.identity_manager.selected_identity is not None
            else (0.0, 0.0)
        )

        reframe_started_at = time()
        if render_preview:
            after_frame, framing_status = self.reframer.render(
                frame, selected_targets, target_velocity
            )
        else:
            framing_status = self.reframer.status(
                frame, selected_targets, target_velocity
            )
            after_frame = frame
        reframe_time_ms = (time() - reframe_started_at) * 1000.0
        preview_started_at = time()
        before_frame = draw_detections(frame, detections) if render_preview else frame
        preview_time_ms = (time() - preview_started_at) * 1000.0
        pipeline_time_ms = (time() - pipeline_started_at) * 1000.0
        pipeline_completed_mark = timestamp_now()
        timestamps.mark(TimestampStage.PIPELINE_COMPLETED, pipeline_completed_mark)
        if self.latency_compensator is not None:
            latency_breakdown, latency_compensation = self.latency_compensator.evaluate(
                timestamps,
                source_fps,
                evaluated_at=pipeline_completed_mark,
            )
        else:
            latency_breakdown, latency_compensation = evaluate_latency_compensation(
                timestamps,
                source_fps,
                evaluated_at=pipeline_completed_mark,
            )
        return FrameData(
            raw_frame=frame,
            before_frame=before_frame,
            after_frame=after_frame,
            detections=detections,
            candidates=candidates,
            selected_targets=selected_targets,
            framing_status=framing_status,
            tracking_status=self.identity_manager.status,
            selected_global_vehicle_id=self.identity_manager.selected_global_vehicle_id,
            selected_local_track_id=self.identity_manager.selected_local_track_id,
            camera_cut_detected=camera_cut,
            lost_frames=self.identity_manager.lost_frames,
            reacquire_score=self.identity_manager.last_reacquire_score,
            reid_confidence_level=self.identity_manager.last_reid_confidence_level,
            motor_safe_to_track=self.identity_manager.motor_safe_to_track,
            identity_decision=self.identity_manager.last_identity_decision,
            identity_decisions=list(self.identity_manager.identity_decisions),
            global_motion=global_motion,
            camera_calibration_profile_id=(
                global_motion.calibration_profile_id if global_motion is not None else None
            ),
            target_velocity=target_velocity,
            timestamps=timestamps,
            latency_breakdown=latency_breakdown,
            latency_compensation=latency_compensation,
            latency_compensation_ms=latency_compensation.applied_latency_ms,
            source_fps=source_fps,
            inference_time_ms=inference_time_ms,
            decode_time_ms=decode_time_ms,
            receive_latency_ms=receive_latency_ms,
            pipeline_time_ms=pipeline_time_ms,
            identity_time_ms=identity_time_ms,
            gmc_time_ms=gmc_time_ms,
            reframe_time_ms=reframe_time_ms,
            preview_time_ms=preview_time_ms,
            skipped_frames=skipped_frames,
        )
