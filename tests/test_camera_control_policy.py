from types import SimpleNamespace
import unittest

from autocamtracker.server.camera_control_policy import (
    CameraControlConfig,
    CameraControlPolicy,
    CameraControlReasonCode,
    CameraControlRequest,
)
from autocamtracker.server.control_policy import ControlPolicy
from autocamtracker.tracking.identity_components import (
    IdentityDecision,
    IdentityReasonCode,
)


class CameraControlPolicyTests(unittest.TestCase):
    def test_dead_zone_and_hysteresis_prevent_axis_chatter(self) -> None:
        policy = CameraControlPolicy(CameraControlConfig(
            low_pass_alpha=1.0,
            max_yaw_acceleration=100.0,
            max_pitch_acceleration=100.0,
        ))

        entered = policy.evaluate(
            CameraControlRequest(True, error_x=0.20), now=0.0
        )
        hysteresis = policy.evaluate(
            CameraControlRequest(True, error_x=0.05), now=0.05
        )
        exited = policy.evaluate(
            CameraControlRequest(True, error_x=0.02), now=0.10
        )

        self.assertTrue(entered.x_axis_active)
        self.assertGreater(entered.yaw_velocity, 0.0)
        self.assertTrue(hysteresis.x_axis_active)
        self.assertEqual(
            hysteresis.reason_code,
            CameraControlReasonCode.HYSTERESIS_TRACKING,
        )
        self.assertFalse(exited.x_axis_active)
        self.assertEqual(exited.yaw_velocity, 0.0)
        self.assertEqual(exited.reason_code, CameraControlReasonCode.DEAD_ZONE)

    def test_low_pass_smoothing_filters_command_steps(self) -> None:
        policy = CameraControlPolicy(CameraControlConfig(
            low_pass_alpha=0.25,
            max_yaw_acceleration=100.0,
            max_pitch_acceleration=100.0,
        ))

        first = policy.evaluate(
            CameraControlRequest(True, error_x=0.20), now=0.0
        )
        second = policy.evaluate(
            CameraControlRequest(True, error_x=0.20), now=0.05
        )

        self.assertAlmostEqual(first.yaw_velocity, 0.05)
        self.assertAlmostEqual(second.yaw_velocity, 0.0875)

    def test_velocity_and_acceleration_are_independently_bounded(self) -> None:
        policy = CameraControlPolicy(CameraControlConfig(
            low_pass_alpha=1.0,
            max_yaw_velocity=0.30,
            max_pitch_velocity=0.20,
            max_yaw_acceleration=1.0,
            max_pitch_acceleration=0.5,
            nominal_interval_seconds=0.10,
            max_interval_seconds=0.10,
        ))

        first = policy.evaluate(
            CameraControlRequest(True, error_x=1.0, error_y=1.0), now=0.0
        )
        second = policy.evaluate(
            CameraControlRequest(True, error_x=1.0, error_y=1.0), now=0.10
        )
        third = policy.evaluate(
            CameraControlRequest(True, error_x=1.0, error_y=1.0), now=0.20
        )

        self.assertAlmostEqual(first.yaw_velocity, 0.10)
        self.assertAlmostEqual(first.pitch_velocity, -0.05)
        self.assertAlmostEqual(first.yaw_acceleration, 1.0)
        self.assertAlmostEqual(first.pitch_acceleration, -0.5)
        self.assertAlmostEqual(second.yaw_velocity, 0.20)
        self.assertAlmostEqual(third.yaw_velocity, 0.30)
        self.assertGreaterEqual(third.pitch_velocity, -0.20)

    def test_zoom_ramps_holds_after_loss_then_returns_to_wide(self) -> None:
        policy = CameraControlPolicy(CameraControlConfig(
            zoom_ramp_per_second=1.0,
            zoom_hold_seconds=0.5,
            nominal_interval_seconds=0.1,
            max_interval_seconds=1.0,
        ))

        first = policy.evaluate(
            CameraControlRequest(True, error_x=0.2, zoom_target=3.0), now=0.0
        )
        second = policy.evaluate(
            CameraControlRequest(True, error_x=0.2, zoom_target=3.0), now=0.1
        )
        held = policy.evaluate(
            CameraControlRequest(False, zoom_target=3.0), now=0.2
        )
        still_held = policy.evaluate(
            CameraControlRequest(False, zoom_target=3.0), now=0.7
        )
        returning = policy.evaluate(
            CameraControlRequest(False, zoom_target=3.0), now=0.8
        )

        self.assertAlmostEqual(first.zoom_output, 1.1)
        self.assertAlmostEqual(second.zoom_output, 1.2)
        self.assertEqual(held.zoom_output, second.zoom_output)
        self.assertEqual(still_held.zoom_output, second.zoom_output)
        self.assertEqual(
            held.reason_code,
            CameraControlReasonCode.TARGET_LOST_ZOOM_HOLD,
        )
        self.assertLess(returning.zoom_output, still_held.zoom_output)
        self.assertEqual(
            returning.reason_code,
            CameraControlReasonCode.TARGET_LOST_ZOOM_RETURN,
        )

    def test_uncertainty_freezes_motion_and_zoom_immediately(self) -> None:
        policy = CameraControlPolicy()
        tracking = policy.evaluate(
            CameraControlRequest(True, error_x=0.5, zoom_target=3.0), now=0.0
        )
        frozen = policy.evaluate(
            CameraControlRequest(
                True,
                error_x=0.8,
                zoom_target=5.0,
                uncertainty_score=0.4,
            ),
            now=0.05,
        )

        self.assertGreater(tracking.yaw_velocity, 0.0)
        self.assertTrue(frozen.frozen)
        self.assertFalse(frozen.target_locked)
        self.assertEqual((frozen.yaw_velocity, frozen.pitch_velocity), (0.0, 0.0))
        self.assertEqual(frozen.zoom_output, tracking.zoom_output)
        self.assertEqual(
            frozen.reason_code,
            CameraControlReasonCode.UNCERTAINTY_FREEZE,
        )

    def test_invalid_configuration_and_requests_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CameraControlConfig(dead_zone_enter=0.03, dead_zone_exit=0.04)
        with self.assertRaises(ValueError):
            CameraControlRequest(True, zoom_target=0.0)


class CameraControlIntegrationTests(unittest.TestCase):
    @staticmethod
    def frame_data(*, motor_safe: bool = True):
        return SimpleNamespace(
            selected_targets=[SimpleNamespace(
                confidence=0.9,
                status="tracking",
                lost_frame_count=0,
                center=(480.0, 180.0),
                bbox=(440.0, 140.0, 520.0, 220.0),
            )],
            tracking_status="tracking",
            motor_safe_to_track=motor_safe,
            framing_status=SimpleNamespace(
                error_x=160.0,
                error_y=0.0,
                framing_mode="medium",
                zoom_target=3.0,
            ),
            selected_global_vehicle_id=3,
            selected_local_track_id=4,
            target_velocity=(0.0, 0.0),
            source_fps=20.0,
            reid_confidence_level="high",
            identity_decision=IdentityDecision(
                IdentityReasonCode.CURRENT_TRACK_MATCH,
                True,
                "tracker_continuity",
                1.0,
                {"tracker_match": 1.0},
                4,
            ),
        )

    def test_control_policy_emits_shaped_command_and_audit_scores(self) -> None:
        camera_policy = CameraControlPolicy()
        policy = ControlPolicy(camera_control_policy=camera_policy)

        decision = policy.frame_command(
            self.frame_data(), (360, 640, 3), sequence=1, now=0.0
        )

        self.assertTrue(decision.payload["target_locked"])
        self.assertLess(decision.payload["error_x"], 0.5)
        self.assertAlmostEqual(decision.payload["zoom_factor"], 1.04)
        self.assertEqual(decision.payload["zoom_target"], 3.0)
        self.assertEqual(
            decision.payload["camera_control"]["reason_code"], "TRACKING"
        )
        self.assertLessEqual(
            abs(decision.payload["camera_control"]["yaw_acceleration"]), 1.20
        )
        self.assertIsNotNone(decision.camera_control)

    def test_identity_uncertainty_emits_frozen_stop_with_zoom_hold(self) -> None:
        camera_policy = CameraControlPolicy()
        policy = ControlPolicy(camera_control_policy=camera_policy)
        tracked = policy.frame_command(
            self.frame_data(), (360, 640, 3), sequence=1, now=0.0
        )
        frozen = policy.frame_command(
            self.frame_data(motor_safe=False),
            (360, 640, 3),
            sequence=2,
            now=0.05,
        )

        self.assertTrue(tracked.payload["target_locked"])
        self.assertFalse(frozen.payload["target_locked"])
        self.assertEqual(frozen.payload["error_x"], 0.0)
        self.assertEqual(
            frozen.payload["camera_control"]["reason_code"],
            "UNCERTAINTY_FREEZE",
        )
        self.assertEqual(
            frozen.payload["zoom_factor"], tracked.payload["zoom_factor"]
        )


if __name__ == "__main__":
    unittest.main()
