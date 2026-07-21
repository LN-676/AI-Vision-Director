from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from autocamtracker.tracking.feature_gallery import DetectionFeatureMatch
from autocamtracker.tracking.identity_components import (
    IdentityReasonCode,
    IdentityLifecycleState,
    IdentityMatcher,
    IdentityStateMachine,
    MotorSafetyPolicy,
    ReacquisitionPolicy,
    TrackIdentityMapper,
)
from autocamtracker.tracking.identity_manager import GlobalIdentityManager
from autocamtracker.vision.detector import TrackedDetection


def detection(track_id: int | None = 12, frame_index: int = 1) -> TrackedDetection:
    return TrackedDetection(
        track_id=track_id,
        bbox=(210.0, 140.0, 290.0, 220.0),
        class_id=2,
        class_name="car",
        confidence=0.88,
        center=(250.0, 180.0),
        frame_index=frame_index,
        timestamp=float(frame_index),
        tracker_name="botsort",
    )


class StaticGallery:
    def __init__(self, score: float) -> None:
        self.score = score

    def has_master_features(self, _vehicle_id: int) -> bool:
        return True

    def rank_detections_for_vehicle(self, _vehicle_id, detections, _frame):
        return [DetectionFeatureMatch(detection=detections[0], score=self.score, matches=[])] if detections else []


class MatcherWithoutOpenCV(IdentityMatcher):
    def color_signature(self, frame, bbox):
        return None

    def _color_similarity(self, identity, candidate, frame) -> float:
        return 0.8


class IdentityComponentTests(unittest.TestCase):
    def test_lifecycle_states_are_explicit_and_complete(self) -> None:
        self.assertEqual(
            {state.name for state in IdentityLifecycleState},
            {"LOCKED", "COASTING", "SEARCHING", "CANDIDATE", "CONFIRMED", "LOST"},
        )

    def test_state_machine_records_transition_boundary(self) -> None:
        machine = IdentityStateMachine()
        machine.transition(IdentityLifecycleState.LOCKED)
        machine.transition(IdentityLifecycleState.COASTING)
        self.assertEqual(machine.state, IdentityLifecycleState.COASTING)
        self.assertEqual(machine.previous_state, IdentityLifecycleState.LOCKED)

    def test_motor_safety_preserves_v177_coasting_and_edge_rules(self) -> None:
        policy = MotorSafetyPolicy()
        identity = SimpleNamespace(last_center=(250.0, 180.0), velocity=(0.0, 0.0), lost_frames=1)
        self.assertTrue(policy.for_coasting(3))
        self.assertFalse(policy.for_coasting(4))
        self.assertTrue(policy.can_predict(identity, (360, 640, 3)))
        identity.last_center = (5.0, 180.0)
        self.assertFalse(policy.can_predict(identity, (360, 640, 3)))

    def test_track_mapper_preserves_local_track_and_iou_mapping(self) -> None:
        mapper = TrackIdentityMapper()
        identity = SimpleNamespace(
            global_vehicle_id=7,
            last_track_id=12,
            last_frame_index=1,
            last_bbox=(210.0, 140.0, 290.0, 220.0),
        )
        self.assertTrue(mapper.is_selected(identity, detection(12)))
        identity.last_track_id = None
        self.assertTrue(mapper.is_selected(identity, detection(None)))

    def test_reacquisition_policy_requires_same_three_frame_confirmation(self) -> None:
        policy = ReacquisitionPolicy()
        identity = SimpleNamespace(
            global_vehicle_id=1,
            last_center=(250.0, 180.0),
            velocity=(0.0, 0.0),
            lost_frames=5,
        )
        frame = np.full((360, 640, 3), 90, dtype=np.uint8)
        candidate = detection(22, 3)
        first = policy.choose(identity, [candidate], frame, StaticGallery(0.78))
        second = policy.choose(identity, [candidate], frame, StaticGallery(0.78))
        third = policy.choose(identity, [candidate], frame, StaticGallery(0.78))
        self.assertEqual(first.state, IdentityLifecycleState.CANDIDATE)
        self.assertEqual(first.reason_code, IdentityReasonCode.GALLERY_PENDING_CONFIRMATION)
        self.assertEqual(first.sub_scores["feature_score"], 0.78)
        self.assertIn("score_margin", first.sub_scores)
        self.assertIn("min_score_threshold", first.sub_scores)
        self.assertEqual(second.confidence_level, "pending")
        self.assertEqual(third.state, IdentityLifecycleState.CONFIRMED)
        self.assertEqual(third.reason_code, IdentityReasonCode.GALLERY_CONFIRMED)
        self.assertIs(third.detection, candidate)

    def test_legacy_matcher_outputs_reason_and_every_weighted_sub_score(self) -> None:
        matcher = MatcherWithoutOpenCV(min_score=0.5, confirm_frames=1)
        identity = SimpleNamespace(
            last_track_id=12,
            last_bbox=(210.0, 140.0, 290.0, 220.0),
            last_center=(250.0, 180.0),
            class_name="car",
        )
        frame = np.full((360, 640, 3), 90, dtype=np.uint8)

        result = matcher.choose_with_decision(identity, [detection(12)], frame)

        self.assertEqual(result.identity.reason_code, IdentityReasonCode.LEGACY_CONFIRMED)
        self.assertTrue(result.identity.accepted)
        self.assertEqual(
            {
                "tracker_match",
                "color_similarity",
                "size_similarity",
                "motion_similarity",
                "detection_confidence",
                "class_match",
                "total_score",
            } - set(result.identity.sub_scores),
            set(),
        )

    def test_manager_outputs_every_attempt_and_final_identity_decision(self) -> None:
        frame = np.full((360, 640, 3), 90, dtype=np.uint8)
        manager = GlobalIdentityManager(
            identity_matcher=MatcherWithoutOpenCV(),
            predictive_coast_frames=3,
        )
        manager.select_detection(detection(12), frame, persist=False)
        self.assertEqual(
            manager.last_identity_decision.reason_code,
            IdentityReasonCode.MANUAL_SELECT_TRANSIENT,
        )
        self.assertEqual(manager.last_identity_decision.sub_scores["gid_reused"], 0.0)

        selected = manager.update([], frame)

        self.assertEqual(selected[0].status, "coasting")
        self.assertEqual(
            [item.reason_code for item in manager.identity_decisions],
            [
                IdentityReasonCode.GALLERY_UNAVAILABLE,
                IdentityReasonCode.LEGACY_NO_CANDIDATE,
                IdentityReasonCode.COASTING_PREDICTION,
            ],
        )
        self.assertEqual(
            manager.last_identity_decision.reason_code,
            IdentityReasonCode.COASTING_PREDICTION,
        )
        self.assertIn("lost_frames", manager.last_identity_decision.sub_scores)
        self.assertIn("motor_safe", manager.last_identity_decision.sub_scores)

        manager.update([detection(12, 2)], frame)
        self.assertEqual(
            manager.last_identity_decision.reason_code,
            IdentityReasonCode.CURRENT_TRACK_MATCH,
        )
        self.assertEqual(manager.last_identity_decision.sub_scores["tracker_match"], 1.0)

    def test_legacy_manager_is_facade_over_all_five_components(self) -> None:
        manager = GlobalIdentityManager()
        self.assertIsInstance(manager.state_machine, IdentityStateMachine)
        self.assertIsInstance(manager.reacquire, IdentityMatcher)
        self.assertIsInstance(manager.reacquisition_policy, ReacquisitionPolicy)
        self.assertIsInstance(manager.track_identity_mapper, TrackIdentityMapper)
        self.assertIsInstance(manager.motor_safety_policy, MotorSafetyPolicy)

    def test_facade_exposes_locked_coasting_searching_and_lost_states(self) -> None:
        frame = np.full((360, 640, 3), 90, dtype=np.uint8)
        manager = GlobalIdentityManager(max_lost_frames=1, predictive_coast_frames=1)
        manager.select_detection(detection(1), frame, persist=False)
        self.assertEqual(manager.identity_state, IdentityLifecycleState.LOCKED)
        manager.update([], frame)
        self.assertEqual(manager.identity_state, IdentityLifecycleState.COASTING)
        manager.handle_camera_cut()
        self.assertEqual(manager.identity_state, IdentityLifecycleState.SEARCHING)
        manager.update([], frame)
        self.assertEqual(manager.identity_state, IdentityLifecycleState.LOST)

    def test_facade_exposes_candidate_and_confirmed_reid_states(self) -> None:
        frame = np.full((360, 640, 3), 90, dtype=np.uint8)
        manager = GlobalIdentityManager(feature_gallery=StaticGallery(0.78))  # type: ignore[arg-type]
        manager.select_detection(detection(1), frame, persist=True)
        manager.handle_camera_cut()
        candidate = detection(22, 3)
        manager.update([candidate], frame)
        self.assertEqual(manager.identity_state, IdentityLifecycleState.CANDIDATE)
        manager.update([candidate], frame)
        manager.update([candidate], frame)
        self.assertEqual(manager.identity_state, IdentityLifecycleState.CONFIRMED)
        self.assertEqual(manager.status, "tracking")


if __name__ == "__main__":
    unittest.main()
