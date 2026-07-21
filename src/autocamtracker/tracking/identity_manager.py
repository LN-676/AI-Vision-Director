"""Global vehicle identity and manual ReID reacquire logic for AI_Vison_Director V1."""

from __future__ import annotations

from dataclasses import dataclass, field

from autocamtracker.tracking.feature_gallery import FeatureGallery
from autocamtracker.tracking.identity_components import (
    IdentityDecision,
    IdentityLifecycleState,
    IdentityMatcher,
    IdentityReasonCode,
    IdentityStateMachine,
    MotorSafetyPolicy,
    ReacquisitionPolicy,
    TrackIdentityMapper,
)
from autocamtracker.tracking.target_tracker import SelectedTarget
from autocamtracker.tracking.vehicle_identity_store import VehicleIdentityStore
from autocamtracker.vision.detector import TrackedDetection


@dataclass
class VehicleIdentity:
    global_vehicle_id: int | None
    last_track_id: int | None
    class_name: str
    confidence: float
    last_bbox: tuple[float, float, float, float]
    last_center: tuple[float, float]
    last_frame_index: int
    last_seen_timestamp: float
    color_signature: object | None = None
    lost_frames: int = 0
    status: str = "tracking"
    track_aliases: list[int] = field(default_factory=list)
    velocity: tuple[float, float] = (0.0, 0.0)
    lifecycle_state: IdentityLifecycleState = IdentityLifecycleState.LOCKED


ReacquireEngine = IdentityMatcher


class GlobalIdentityManager:
    """Keeps selected GID independent from local tracker IDs."""

    def __init__(
        self,
        max_lost_frames: int = 150,
        searching_after_frames: int = 5,
        predictive_coast_frames: int = 12,
        coasting_min_confidence: float = 0.24,
        identity_store: VehicleIdentityStore | None = None,
        feature_gallery: FeatureGallery | None = None,
        state_machine: IdentityStateMachine | None = None,
        identity_matcher: IdentityMatcher | None = None,
        reacquisition_policy: ReacquisitionPolicy | None = None,
        track_identity_mapper: TrackIdentityMapper | None = None,
        motor_safety_policy: MotorSafetyPolicy | None = None,
    ) -> None:
        self.max_lost_frames = max_lost_frames
        self.searching_after_frames = searching_after_frames
        self.predictive_coast_frames = predictive_coast_frames
        self.coasting_min_confidence = max(0.20, min(0.50, coasting_min_confidence))
        self.next_global_vehicle_id = 1
        self.identity_store = identity_store
        self.feature_gallery = feature_gallery
        self.selected_identity: VehicleIdentity | None = None
        self.state_machine = state_machine or IdentityStateMachine()
        self.reacquire = identity_matcher or IdentityMatcher()
        self.reacquisition_policy = reacquisition_policy or ReacquisitionPolicy()
        self.track_identity_mapper = track_identity_mapper or TrackIdentityMapper()
        self.motor_safety_policy = motor_safety_policy or MotorSafetyPolicy()
        self.status = "idle"
        self.last_reacquire_score = 0.0
        self.camera_cut_seen = False
        self.auto_reid_min_score = 0.72
        self.auto_reid_high_score = 0.84
        self.auto_reid_low_score = 0.58
        self.auto_reid_margin = 0.08
        self.auto_reid_confirm_frames = 3
        self.last_reid_confidence_level = "unknown"
        self.motor_safe_to_track = True
        self.identity_decisions: list[IdentityDecision] = []
        self.last_identity_decision = IdentityDecision(
            IdentityReasonCode.IDLE_NO_IDENTITY, False, "identity_manager", 0.0, {}
        )
        self._auto_reid_pending_track_id: int | None = None
        self._auto_reid_pending_count = 0

    @property
    def identity_state(self) -> IdentityLifecycleState | None:
        return self.state_machine.state

    def _transition(self, state: IdentityLifecycleState) -> None:
        self.state_machine.transition(state)
        if self.selected_identity is not None:
            self.selected_identity.lifecycle_state = state

    @property
    def selected_global_vehicle_id(self) -> int | None:
        return self.selected_identity.global_vehicle_id if self.selected_identity is not None else None

    @property
    def selected_local_track_id(self) -> int | None:
        return self.selected_identity.last_track_id if self.selected_identity is not None else None

    @property
    def lost_frames(self) -> int:
        return self.selected_identity.lost_frames if self.selected_identity is not None else 0

    def reset(self) -> None:
        self.selected_identity = None
        self.status = "idle"
        self.last_reacquire_score = 0.0
        self.last_reid_confidence_level = "unknown"
        self.motor_safe_to_track = True
        self.camera_cut_seen = False
        self.reacquire.reset_pending()
        self._reset_auto_reid_pending()
        self.state_machine.reset()
        self._begin_decisions()
        self._record_decision(IdentityDecision(
            IdentityReasonCode.RESET, False, "identity_manager", 0.0, {}
        ))

    def set_auto_reid_threshold(self, min_score: float) -> None:
        self.auto_reid_min_score = max(0.0, min(1.0, float(min_score)))
        self.auto_reid_high_score = max(self.auto_reid_min_score, min(1.0, self.auto_reid_min_score + 0.12))
        self.auto_reid_low_score = max(0.0, min(self.auto_reid_min_score, self.auto_reid_min_score - 0.14))
        self.reacquisition_policy.set_min_score(self.auto_reid_min_score)
        self._reset_auto_reid_pending()

    def select_detection(self, detection: TrackedDetection, frame, persist: bool = True) -> VehicleIdentity:
        self._begin_decisions()
        reuse_existing_gid = bool(
            persist
            and self.selected_identity is not None
            and self.selected_identity.global_vehicle_id is not None
            and detection.track_id is not None
            and detection.track_id == self.selected_identity.last_track_id
        )
        color_signature = self.reacquire.color_signature(frame, detection.bbox)
        global_vehicle_id = self._resolve_global_vehicle_id(detection) if persist else None
        identity = self._identity_from_detection(global_vehicle_id, detection, color_signature)
        self.selected_identity = identity
        self.status = "tracking"
        self.last_reacquire_score = 1.0
        self.camera_cut_seen = False
        self.reacquire.reset_pending()
        self._reset_auto_reid_pending()
        self._transition(IdentityLifecycleState.LOCKED)
        reason_code = (
            IdentityReasonCode.MANUAL_SELECT_TRANSIENT
            if not persist
            else IdentityReasonCode.MANUAL_SELECT_EXISTING_GID
            if reuse_existing_gid
            else IdentityReasonCode.MANUAL_SELECT_NEW_GID
        )
        self._record_decision(IdentityDecision(
            reason_code,
            True,
            "manual_selection",
            1.0,
            {
                "manual_override": 1.0,
                "detection_confidence": detection.confidence,
                "persisted": float(persist),
                "gid_reused": float(reuse_existing_gid),
            },
            detection.track_id,
        ))
        return identity

    def link_detection(self, vehicle_id: int, detection: TrackedDetection, frame) -> VehicleIdentity | None:
        self._begin_decisions()
        if self.identity_store is not None and self.identity_store.get_vehicle(vehicle_id) is None:
            self._record_decision(IdentityDecision(
                IdentityReasonCode.MANUAL_LINK_GID_NOT_FOUND,
                False,
                "manual_link",
                0.0,
                {"gid_exists": 0.0, "manual_override": 1.0},
                detection.track_id,
            ))
            return None
        color_signature = self.reacquire.color_signature(frame, detection.bbox)
        if self.identity_store is not None:
            self.identity_store.update_vehicle(vehicle_id, detection, {"linked_manually": True})
        identity = self._identity_from_detection(vehicle_id, detection, color_signature)
        self.selected_identity = identity
        self.status = "tracking"
        self.last_reacquire_score = 1.0
        self.camera_cut_seen = False
        self.reacquire.reset_pending()
        self._reset_auto_reid_pending()
        self._transition(IdentityLifecycleState.LOCKED)
        self._record_decision(IdentityDecision(
            IdentityReasonCode.MANUAL_LINK,
            True,
            "manual_link",
            1.0,
            {
                "gid_exists": 1.0,
                "manual_override": 1.0,
                "detection_confidence": detection.confidence,
            },
            detection.track_id,
        ))
        return identity

    def select_stored_vehicle(
        self,
        vehicle_id: int,
        detections: list[TrackedDetection],
        frame,
        min_score: float = 0.72,
    ) -> tuple[VehicleIdentity | None, float]:
        self._begin_decisions()
        if self.identity_store is None:
            self._record_decision(IdentityDecision(
                IdentityReasonCode.STORED_GID_NOT_FOUND,
                False,
                "stored_gid",
                0.0,
                {"identity_store_available": 0.0},
            ))
            return None, 0.0

        stored = self.identity_store.get_vehicle(vehicle_id)
        if stored is None:
            self._record_decision(IdentityDecision(
                IdentityReasonCode.STORED_GID_NOT_FOUND,
                False,
                "stored_gid",
                0.0,
                {"identity_store_available": 1.0, "gid_exists": 0.0},
            ))
            return None, 0.0

        ranked = (
            self.feature_gallery.rank_detections_for_vehicle(vehicle_id, detections, frame)
            if self.feature_gallery is not None
            else []
        )
        best = ranked[0] if ranked else None
        second_score = ranked[1].score if len(ranked) > 1 else 0.0
        if best is not None and best.score >= min_score:
            color_signature = self.reacquire.color_signature(frame, best.detection.bbox)
            identity = self._identity_from_detection(vehicle_id, best.detection, color_signature)
            self.selected_identity = identity
            self.status = "tracking"
            self.last_reacquire_score = best.score
            self.camera_cut_seen = False
            self.reacquire.reset_pending()
            self._reset_auto_reid_pending()
            self._transition(IdentityLifecycleState.CONFIRMED)
            if self.identity_store is not None:
                self.identity_store.update_vehicle(vehicle_id, best.detection, {"matched_by": "master_feature_gallery"})
            self._record_decision(IdentityDecision(
                IdentityReasonCode.STORED_REID_CONFIRMED,
                True,
                "stored_gid",
                best.score,
                {
                    "feature_score": best.score,
                    "second_best_score": second_score,
                    "score_margin": best.score - second_score,
                    "min_score_threshold": min_score,
                    "candidate_count": float(len(ranked)),
                },
                best.detection.track_id,
            ))
            return identity, best.score

        if self._should_preserve_selected_vehicle(vehicle_id):
            self.last_reacquire_score = best.score if best is not None else self.last_reacquire_score
            self._reset_auto_reid_pending()
            self._record_decision(IdentityDecision(
                IdentityReasonCode.STORED_ACTIVE_TRACK_PRESERVED,
                True,
                "stored_gid",
                self.last_reacquire_score,
                {
                    "feature_score": best.score if best is not None else 0.0,
                    "min_score_threshold": min_score,
                    "active_track": 1.0,
                    "lost_frames": float(self.lost_frames),
                },
                self.selected_local_track_id,
            ))
            return self.selected_identity, self.last_reacquire_score

        identity = VehicleIdentity(
            global_vehicle_id=vehicle_id,
            last_track_id=None,
            class_name=stored.class_name,
            confidence=stored.confidence,
            last_bbox=stored.bbox,
            last_center=stored.center,
            last_frame_index=stored.last_frame_index,
            last_seen_timestamp=stored.last_seen_timestamp,
            color_signature=None,
            lost_frames=self.searching_after_frames,
            status="searching",
            track_aliases=[],
        )
        self.selected_identity = identity
        self.status = "searching"
        self.last_reacquire_score = best.score if best is not None else 0.0
        self.camera_cut_seen = False
        self.reacquire.reset_pending()
        self._reset_auto_reid_pending()
        self._transition(IdentityLifecycleState.SEARCHING)
        self._record_decision(IdentityDecision(
            IdentityReasonCode.STORED_GID_SEARCHING,
            False,
            "stored_gid",
            self.last_reacquire_score,
            {
                "feature_score": best.score if best is not None else 0.0,
                "second_best_score": second_score,
                "min_score_threshold": min_score,
                "candidate_count": float(len(ranked)),
            },
            best.detection.track_id if best is not None else None,
        ))
        return identity, self.last_reacquire_score

    def _should_preserve_selected_vehicle(self, vehicle_id: int) -> bool:
        identity = self.selected_identity
        return bool(
            identity is not None
            and identity.global_vehicle_id == vehicle_id
            and identity.last_track_id is not None
            and self.status == "tracking"
            and identity.status in {"tracking", "coasting"}
            and not self.camera_cut_seen
            and identity.lost_frames <= self.predictive_coast_frames
        )

    def handle_camera_cut(self) -> None:
        self._begin_decisions()
        if self.selected_identity is None:
            self._record_decision(IdentityDecision(
                IdentityReasonCode.IDLE_NO_IDENTITY, False, "camera_cut", 0.0, {}
            ))
            return
        self.selected_identity.last_track_id = None
        self.selected_identity.status = "camera_cut"
        self.status = "camera_cut"
        self.camera_cut_seen = True
        self.reacquire.reset_pending()
        self._reset_auto_reid_pending()
        self._transition(IdentityLifecycleState.SEARCHING)
        self._record_decision(IdentityDecision(
            IdentityReasonCode.CAMERA_CUT,
            False,
            "camera_cut",
            0.0,
            {"camera_cut_detected": 1.0, "track_retained": 0.0},
        ))

    def update(self, detections: list[TrackedDetection], frame) -> list[SelectedTarget]:
        self._begin_decisions()
        if self.camera_cut_seen:
            self._record_decision(IdentityDecision(
                IdentityReasonCode.CAMERA_CUT,
                False,
                "camera_cut",
                0.0,
                {"camera_cut_detected": 1.0, "track_retained": 0.0},
            ))
        if self.selected_identity is None:
            self.status = "idle"
            self.last_reacquire_score = 0.0
            self.last_reid_confidence_level = "unknown"
            self.motor_safe_to_track = True
            self._record_decision(IdentityDecision(
                IdentityReasonCode.IDLE_NO_IDENTITY,
                False,
                "identity_manager",
                0.0,
                {"detection_count": float(len(detections))},
            ))
            return []

        target = self._find_by_current_track(detections)
        if target is None:
            target, score = self._choose_auto_reid_target(detections, frame)
            if target is None and not self._selected_gid_has_master_features():
                legacy_decision = self.reacquire.choose_with_decision(
                    self.selected_identity, detections, frame
                )
                self._record_decision(legacy_decision.identity)
                target, score = legacy_decision.detection, legacy_decision.identity.score
                if target is not None:
                    self.last_reid_confidence_level = "confirmed"
                    self.motor_safe_to_track = True
            self.last_reacquire_score = score
        else:
            self.last_reacquire_score = 1.0
            self.last_reid_confidence_level = "high"
            self.motor_safe_to_track = True
            self._reset_auto_reid_pending()
            self._record_decision(IdentityDecision(
                IdentityReasonCode.CURRENT_TRACK_MATCH,
                True,
                "tracker_continuity",
                1.0,
                {
                    "tracker_match": 1.0,
                    "detection_confidence": target.confidence,
                    "motor_safe": 1.0,
                },
                target.track_id,
            ))

        if target is not None:
            self._update_identity(target, frame)
            self.status = "tracking"
            self.selected_identity.status = "tracking"
            self.motor_safe_to_track = self.motor_safety_policy.for_match(self.last_reid_confidence_level)
            self.camera_cut_seen = False
            matched_state = (
                IdentityLifecycleState.CONFIRMED
                if self.last_reid_confidence_level == "confirmed"
                else IdentityLifecycleState.LOCKED
            )
            self._transition(matched_state)
            return [self._selected_target_from_detection(target, "tracking")]

        identity = self.selected_identity
        identity.lost_frames += 1
        if (
            not self.camera_cut_seen
            and identity.lost_frames <= self.predictive_coast_frames
            and self.motor_safety_policy.can_predict(identity, frame.shape)
        ):
            self.status = "tracking"
            identity.status = "coasting"
            self.last_reid_confidence_level = "coasting"
            self.motor_safe_to_track = self.motor_safety_policy.for_coasting(identity.lost_frames)
            self._transition(IdentityLifecycleState.COASTING)
            self._record_decision(IdentityDecision(
                IdentityReasonCode.COASTING_PREDICTION,
                self.motor_safe_to_track,
                "motion_prediction",
                max(0.0, 1.0 - identity.lost_frames / max(1, self.predictive_coast_frames)),
                {
                    "lost_frames": float(identity.lost_frames),
                    "coast_frame_limit": float(self.predictive_coast_frames),
                    "prediction_safe": 1.0,
                    "motor_safe": float(self.motor_safe_to_track),
                },
                identity.last_track_id,
            ))
            return [self._coasted_selected_target(frame.shape)]
        if self.camera_cut_seen:
            self.status = "camera_cut"
        elif identity.lost_frames > self.max_lost_frames:
            self.status = "lost"
        elif identity.lost_frames >= self.searching_after_frames:
            self.status = "searching"
        else:
            self.status = "tracking"
        identity.status = self.status
        was_candidate = self.identity_state == IdentityLifecycleState.CANDIDATE
        if self.last_reid_confidence_level not in {"low", "candidate"}:
            self.last_reid_confidence_level = "lost"
        self.motor_safe_to_track = False
        if identity.lost_frames > self.max_lost_frames:
            self._transition(IdentityLifecycleState.LOST)
            reason_code = IdentityReasonCode.LOST_MAX_FRAMES
        elif was_candidate or self.last_reid_confidence_level == "candidate":
            self._transition(IdentityLifecycleState.CANDIDATE)
            reason_code = IdentityReasonCode.SEARCHING_CANDIDATE
        else:
            self._transition(IdentityLifecycleState.SEARCHING)
            reason_code = IdentityReasonCode.SEARCHING_NO_MATCH
        self._record_decision(IdentityDecision(
            reason_code,
            False,
            "identity_state",
            self.last_reacquire_score,
            {
                "reacquire_score": self.last_reacquire_score,
                "lost_frames": float(identity.lost_frames),
                "searching_after_frames": float(self.searching_after_frames),
                "max_lost_frames": float(self.max_lost_frames),
                "motor_safe": 0.0,
            },
            identity.last_track_id,
        ))
        return [self._selected_target_from_identity()]

    def _choose_auto_reid_target(
        self,
        detections: list[TrackedDetection],
        frame,
    ) -> tuple[TrackedDetection | None, float]:
        policy = self.reacquisition_policy
        policy.min_score = self.auto_reid_min_score
        policy.high_score = self.auto_reid_high_score
        policy.low_score = self.auto_reid_low_score
        policy.margin = self.auto_reid_margin
        policy.confirm_frames = self.auto_reid_confirm_frames
        decision = policy.choose(self.selected_identity, detections, frame, self.feature_gallery)
        self._record_decision(decision.as_identity_decision())
        self.last_reid_confidence_level = decision.confidence_level
        self.motor_safe_to_track = self.motor_safety_policy.for_match(decision.confidence_level)
        if decision.state in {IdentityLifecycleState.CANDIDATE, IdentityLifecycleState.CONFIRMED}:
            self._transition(decision.state)
        return decision.detection, decision.score

    def _begin_decisions(self) -> None:
        self.identity_decisions = []

    def _record_decision(self, decision: IdentityDecision) -> None:
        self.identity_decisions.append(decision)
        self.last_identity_decision = decision

    def _selected_gid_has_master_features(self) -> bool:
        identity = self.selected_identity
        return bool(
            identity is not None
            and identity.global_vehicle_id is not None
            and self.feature_gallery is not None
            and self.feature_gallery.has_master_features(identity.global_vehicle_id)
        )

    def _reset_auto_reid_pending(self) -> None:
        self._auto_reid_pending_track_id = None
        self._auto_reid_pending_count = 0
        self.reacquisition_policy.reset_pending()

    def is_selected_detection(self, detection: TrackedDetection) -> bool:
        return self.track_identity_mapper.is_selected(self.selected_identity, detection)

    def global_id_for_detection(self, detection: TrackedDetection) -> int | None:
        if self.is_selected_detection(detection):
            return self.selected_global_vehicle_id
        return None

    def _resolve_global_vehicle_id(self, detection: TrackedDetection) -> int:
        if (
            self.selected_identity is not None
            and self.selected_identity.global_vehicle_id is not None
            and detection.track_id is not None
            and detection.track_id == self.selected_identity.last_track_id
        ):
            if self.identity_store is not None:
                self.identity_store.update_vehicle(self.selected_identity.global_vehicle_id, detection)
            return self.selected_identity.global_vehicle_id

        if self.identity_store is None:
            global_vehicle_id = self.next_global_vehicle_id
            self.next_global_vehicle_id += 1
            return global_vehicle_id

        return self.identity_store.create_vehicle(detection)

    def _find_by_current_track(self, detections: list[TrackedDetection]) -> TrackedDetection | None:
        return self.reacquire.find_current_track(self.selected_identity, detections)

    @staticmethod
    def _reid_pending_key(detection: TrackedDetection) -> int:
        if detection.track_id is not None:
            return int(detection.track_id)
        x1, y1, x2, y2 = detection.bbox
        center_x = int(round((x1 + x2) / 20.0))
        center_y = int(round((y1 + y2) / 20.0))
        return hash((center_x, center_y))

    @staticmethod
    def _bbox_iou(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> float:
        left = max(first[0], second[0])
        top = max(first[1], second[1])
        right = min(first[2], second[2])
        bottom = min(first[3], second[3])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union > 0.0 else 0.0

    def _update_identity(self, detection: TrackedDetection, frame) -> None:
        if self.selected_identity is None:
            return
        identity = self.selected_identity
        self.track_identity_mapper.update(identity, detection)
        signature = self.reacquire.color_signature(frame, detection.bbox)
        if signature is not None:
            identity.color_signature = signature
        if self.identity_store is not None and identity.global_vehicle_id is not None:
            self.identity_store.update_vehicle(identity.global_vehicle_id, detection)

    def _spatial_reid_candidates(
        self,
        identity: VehicleIdentity,
        detections: list[TrackedDetection],
        frame_shape,
    ) -> list[TrackedDetection]:
        return self.reacquisition_policy.spatial_candidates(identity, detections, frame_shape)

    def _can_predict_safely(self, identity: VehicleIdentity, frame_shape) -> bool:
        return self.motor_safety_policy.can_predict(identity, frame_shape)

    def _coasted_selected_target(self, frame_shape) -> SelectedTarget:
        assert self.selected_identity is not None
        identity = self.selected_identity
        frame_h, frame_w = frame_shape[:2]
        lost = max(1, identity.lost_frames)
        dx = identity.velocity[0] * lost
        dy = identity.velocity[1] * lost
        x1, y1, x2, y2 = identity.last_bbox
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        center_x = max(width / 2.0, min(frame_w - width / 2.0, identity.last_center[0] + dx))
        center_y = max(height / 2.0, min(frame_h - height / 2.0, identity.last_center[1] + dy))
        bbox = (
            center_x - width / 2.0,
            center_y - height / 2.0,
            center_x + width / 2.0,
            center_y + height / 2.0,
        )
        if lost <= 3:
            confidence = identity.confidence
        else:
            decay_progress = min(1.0, (lost - 3) / max(1, self.predictive_coast_frames - 3))
            confidence = identity.confidence * (1.0 - 0.70 * decay_progress)
        return SelectedTarget(
            track_id=identity.last_track_id if identity.last_track_id is not None else -1,
            bbox=bbox,
            class_name=identity.class_name,
            confidence=max(self.coasting_min_confidence, confidence),
            center=(center_x, center_y),
            status="coasting",
            lost_frame_count=lost,
        )

    def _identity_from_detection(
        self,
        vehicle_id: int | None,
        detection: TrackedDetection,
        color_signature: object | None,
    ) -> VehicleIdentity:
        return VehicleIdentity(
            global_vehicle_id=vehicle_id,
            last_track_id=detection.track_id,
            class_name=detection.class_name,
            confidence=detection.confidence,
            last_bbox=detection.bbox,
            last_center=detection.center,
            last_frame_index=detection.frame_index,
            last_seen_timestamp=detection.timestamp,
            color_signature=color_signature,
            track_aliases=[] if detection.track_id is None else [detection.track_id],
        )

    @staticmethod
    def _selected_target_from_detection(
        detection: TrackedDetection,
        status: str,
    ) -> SelectedTarget:
        return SelectedTarget(
            track_id=detection.track_id if detection.track_id is not None else -1,
            bbox=detection.bbox,
            class_name=detection.class_name,
            confidence=detection.confidence,
            center=detection.center,
            status=status,  # type: ignore[arg-type]
            lost_frame_count=0,
        )

    def _selected_target_from_identity(self) -> SelectedTarget:
        assert self.selected_identity is not None
        identity = self.selected_identity
        status = "lost" if self.status in {"searching", "camera_cut", "lost"} else "tracking"
        return SelectedTarget(
            track_id=identity.last_track_id if identity.last_track_id is not None else -1,
            bbox=identity.last_bbox,
            class_name=identity.class_name,
            confidence=identity.confidence,
            center=identity.last_center,
            status=status,  # type: ignore[arg-type]
            lost_frame_count=identity.lost_frames,
        )
