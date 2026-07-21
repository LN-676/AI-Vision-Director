from types import SimpleNamespace
import unittest

from autocamtracker.server.control_policy import ControlPolicy
from autocamtracker.vision.framing_engine import (
    FramingEngine,
    FramingEngineConfig,
    FramingReasonCode,
)
from autocamtracker.vision.reframer import FramingConfig, Reframer


def deterministic_engine() -> FramingEngine:
    return FramingEngine(FramingEngineConfig(
        center_smoothing=1.0,
        zoom_smoothing=1.0,
        movement_dead_zone_ratio=0.0,
    ))


class FramingEngineTests(unittest.TestCase):
    def test_static_anchor_achieves_desired_subject_scale_and_zoom(self) -> None:
        decision = deterministic_engine().plan(
            frame_size=(1000, 563),
            subject_bboxes=[(440.0, 240.0, 560.0, 320.0)],
            framing_mode="medium",
        )

        self.assertEqual(decision.framing_anchor, (0.5, 0.5))
        self.assertEqual(decision.lead_room, (0.0, 0.0))
        self.assertEqual(decision.desired_subject_scale, 0.48)
        self.assertAlmostEqual(decision.actual_subject_scale, 0.48)
        self.assertAlmostEqual(decision.zoom_target, 4.0)
        self.assertEqual(decision.reason_code, FramingReasonCode.STATIC_ANCHOR)

    def test_velocity_moves_anchor_opposite_travel_direction_for_lead_room(self) -> None:
        engine = deterministic_engine()
        moving_right = engine.plan(
            frame_size=(1000, 563),
            subject_bboxes=[(440.0, 240.0, 560.0, 320.0)],
            velocity=(20.0, 0.0),
            framing_mode="medium",
        )
        engine.reset()
        moving_left = engine.plan(
            frame_size=(1000, 563),
            subject_bboxes=[(440.0, 240.0, 560.0, 320.0)],
            velocity=(-20.0, 0.0),
            framing_mode="medium",
        )

        self.assertAlmostEqual(moving_right.framing_anchor[0], 0.38)
        self.assertAlmostEqual(moving_right.lead_room[0], 0.12)
        self.assertAlmostEqual(moving_right.realized_anchor[0], 0.38, places=2)
        self.assertGreater(moving_right.crop_window[0], 375)
        self.assertAlmostEqual(moving_left.framing_anchor[0], 0.62)
        self.assertLess(moving_left.lead_room[0], 0.0)
        self.assertEqual(moving_right.reason_code, FramingReasonCode.VELOCITY_LEAD)

    def test_modes_produce_increasing_subject_scale_and_zoom_targets(self) -> None:
        decisions = []
        for mode in ("wide", "medium", "close"):
            engine = deterministic_engine()
            decisions.append(engine.plan(
                frame_size=(1000, 563),
                subject_bboxes=[(440.0, 240.0, 560.0, 320.0)],
                framing_mode=mode,
            ))

        self.assertEqual(
            [item.desired_subject_scale for item in decisions],
            [0.30, 0.48, 0.68],
        )
        self.assertLess(decisions[0].zoom_target, decisions[1].zoom_target)
        self.assertLess(decisions[1].zoom_target, decisions[2].zoom_target)

    def test_tall_subject_limits_zoom_to_keep_bbox_in_frame(self) -> None:
        decision = deterministic_engine().plan(
            frame_size=(1000, 563),
            subject_bboxes=[(450.0, 130.0, 550.0, 430.0)],
            framing_mode="medium",
        )

        self.assertLess(decision.zoom_target, 2.0)
        self.assertLess(decision.actual_subject_scale, decision.desired_subject_scale)

    def test_frame_edge_reports_boundary_clamp_and_realized_anchor(self) -> None:
        decision = deterministic_engine().plan(
            frame_size=(1000, 563),
            subject_bboxes=[(0.0, 240.0, 100.0, 320.0)],
            velocity=(-30.0, 0.0),
            framing_mode="medium",
        )

        self.assertTrue(decision.boundary_clamped)
        self.assertEqual(decision.crop_window[0], 0)
        self.assertNotEqual(decision.realized_anchor, decision.framing_anchor)
        self.assertEqual(decision.reason_code, FramingReasonCode.BOUNDARY_CLAMPED)

    def test_no_subject_returns_full_frame_without_resetting_contract(self) -> None:
        decision = deterministic_engine().plan(
            frame_size=(640, 360),
            subject_bboxes=[],
            framing_mode="wide",
        )

        self.assertEqual(decision.crop_window, (0, 0, 640, 360))
        self.assertIsNone(decision.subject_center)
        self.assertEqual(decision.zoom_target, 1.0)
        self.assertEqual(decision.reason_code, FramingReasonCode.NO_SUBJECT)

    def test_zoom_target_is_smoothed_between_subject_scale_changes(self) -> None:
        engine = FramingEngine(FramingEngineConfig(
            center_smoothing=1.0,
            zoom_smoothing=0.5,
            movement_dead_zone_ratio=0.0,
        ))
        first = engine.plan(
            frame_size=(1000, 563),
            subject_bboxes=[(400.0, 240.0, 600.0, 320.0)],
            framing_mode="medium",
        )
        second = engine.plan(
            frame_size=(1000, 563),
            subject_bboxes=[(450.0, 240.0, 550.0, 320.0)],
            framing_mode="medium",
        )

        self.assertAlmostEqual(first.zoom_target, 2.4)
        self.assertAlmostEqual(second.raw_zoom_target, 4.8)
        self.assertAlmostEqual(second.zoom_target, 3.6)

    def test_invalid_bbox_and_configuration_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FramingEngineConfig(max_horizontal_lead=0.6)
        with self.assertRaises(ValueError):
            deterministic_engine().plan(
                frame_size=(640, 360),
                subject_bboxes=[(10.0, 20.0, 5.0, 30.0)],
            )


class FramingIntegrationTests(unittest.TestCase):
    def test_reframer_exposes_engine_decision_and_anchor_relative_error(self) -> None:
        reframer = Reframer(
            FramingConfig(output_width=1000, output_height=563),
            engine=deterministic_engine(),
        )
        frame = SimpleNamespace(shape=(563, 1000, 3))
        target = SimpleNamespace(bbox=(440.0, 240.0, 560.0, 320.0))

        status = reframer.status(frame, [target], velocity=(20.0, 0.0))

        self.assertAlmostEqual(status.framing_anchor[0], 0.38)
        self.assertAlmostEqual(status.error_x, 120.0)
        self.assertAlmostEqual(status.zoom_target, 4.0)
        self.assertEqual(status.to_dict()["reason_code"], "VELOCITY_LEAD")

    def test_control_uses_dynamic_zoom_target_and_emits_framing_scores(self) -> None:
        frame_data = SimpleNamespace(
            selected_targets=[SimpleNamespace(
                confidence=0.9,
                status="tracking",
                lost_frame_count=0,
                center=(320.0, 180.0),
                bbox=(280.0, 140.0, 360.0, 220.0),
            )],
            tracking_status="tracking",
            motor_safe_to_track=True,
            framing_status=SimpleNamespace(
                error_x=0.0,
                error_y=0.0,
                framing_mode="medium",
                framing_anchor=(0.38, 0.5),
                lead_room=(0.12, 0.0),
                desired_subject_scale=0.48,
                actual_subject_scale=0.46,
                zoom_target=3.2,
                reason_code=FramingReasonCode.VELOCITY_LEAD,
            ),
            selected_global_vehicle_id=3,
            selected_local_track_id=4,
            target_velocity=(0.0, 0.0),
            source_fps=30.0,
            identity_decision=None,
            reid_confidence_level="high",
        )

        decision = ControlPolicy().frame_command(frame_data, (360, 640, 3))

        self.assertEqual(decision.payload["zoom_factor"], 3.2)
        self.assertEqual(decision.payload["zoom_target"], 3.2)
        self.assertEqual(decision.payload["framing_anchor"], (0.38, 0.5))
        self.assertEqual(decision.payload["framing_reason_code"], "VELOCITY_LEAD")


if __name__ == "__main__":
    unittest.main()
