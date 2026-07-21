from types import SimpleNamespace
import unittest

from autocamtracker.core.timestamps import (
    FrameTimeline,
    LatencyCompensator,
    LatencyReasonCode,
    TimestampMark,
    TimestampStage,
)
from autocamtracker.server.control_policy import ControlPolicy


def mark(wall_ms: float, monotonic_ms: float) -> TimestampMark:
    return TimestampMark(wall_ms, monotonic_ms)


def remote_timeline() -> FrameTimeline:
    timeline = FrameTimeline(
        frame_id=7,
        source_id="iphone",
        capture_timestamp_ms=100_000.0,
    )
    timeline.mark(TimestampStage.RECEIVED, mark(100_050.0, 1_000.0))
    timeline.mark(TimestampStage.DECODE_STARTED, mark(100_050.0, 1_000.0))
    timeline.mark(TimestampStage.DECODE_COMPLETED, mark(100_055.0, 1_005.0))
    timeline.mark(TimestampStage.FRAME_DEQUEUED, mark(100_060.0, 1_010.0))
    timeline.mark(TimestampStage.INFERENCE_STARTED, mark(100_060.0, 1_010.0))
    timeline.mark(TimestampStage.INFERENCE_COMPLETED, mark(100_080.0, 1_030.0))
    timeline.mark(TimestampStage.PIPELINE_STARTED, mark(100_082.0, 1_032.0))
    timeline.mark(TimestampStage.PIPELINE_COMPLETED, mark(100_092.0, 1_042.0))
    return timeline


class FrameTimelineTests(unittest.TestCase):
    def test_remote_pipeline_has_non_overlapping_end_to_end_latency(self) -> None:
        breakdown = remote_timeline().latency_breakdown(
            evaluated_at=mark(100_100.0, 1_050.0)
        )

        self.assertEqual(breakdown.transport_ms, 50.0)
        self.assertEqual(breakdown.decode_ms, 5.0)
        self.assertEqual(breakdown.inference_queue_ms, 5.0)
        self.assertEqual(breakdown.inference_ms, 20.0)
        self.assertEqual(breakdown.pipeline_queue_ms, 2.0)
        self.assertEqual(breakdown.pipeline_ms, 10.0)
        self.assertEqual(breakdown.publish_queue_ms, 8.0)
        self.assertEqual(breakdown.end_to_end_ms, 100.0)
        self.assertEqual(breakdown.reason_code, LatencyReasonCode.COMPLETE)

    def test_local_source_uses_monotonic_capture_age(self) -> None:
        timeline = FrameTimeline.local(3, "webcam", mark(10_000.0, 500.0))
        timeline.mark(TimestampStage.CAPTURE_COMPLETED, mark(10_004.0, 504.0))
        timeline.mark(TimestampStage.INFERENCE_STARTED, mark(10_005.0, 505.0))
        timeline.mark(TimestampStage.INFERENCE_COMPLETED, mark(10_015.0, 515.0))
        timeline.mark(TimestampStage.PIPELINE_STARTED, mark(10_016.0, 516.0))
        timeline.mark(TimestampStage.PIPELINE_COMPLETED, mark(10_020.0, 520.0))

        breakdown = timeline.latency_breakdown(
            evaluated_at=mark(10_025.0, 525.0)
        )

        self.assertIsNone(breakdown.transport_ms)
        self.assertEqual(breakdown.capture_ms, 4.0)
        self.assertEqual(breakdown.end_to_end_ms, 25.0)
        self.assertEqual(breakdown.reason_code, LatencyReasonCode.LOCAL_SOURCE)

    def test_clock_skew_is_rejected_instead_of_becoming_negative_latency(self) -> None:
        timeline = FrameTimeline(
            frame_id=1,
            source_id="iphone",
            capture_timestamp_ms=101_000.0,
        )
        timeline.mark(TimestampStage.RECEIVED, mark(100_000.0, 2_000.0))

        breakdown = timeline.latency_breakdown(
            evaluated_at=mark(100_040.0, 2_040.0)
        )

        self.assertIsNone(breakdown.transport_ms)
        self.assertEqual(breakdown.end_to_end_ms, 40.0)
        self.assertEqual(
            breakdown.reason_code, LatencyReasonCode.CLOCK_SKEW_REJECTED
        )

    def test_missing_remote_capture_timestamp_keeps_local_latency(self) -> None:
        timeline = FrameTimeline(frame_id=2, source_id="iphone")
        timeline.mark(TimestampStage.RECEIVED, mark(200_000.0, 3_000.0))

        breakdown = timeline.latency_breakdown(
            evaluated_at=mark(200_030.0, 3_030.0)
        )

        self.assertIsNone(breakdown.transport_ms)
        self.assertEqual(breakdown.end_to_end_ms, 30.0)
        self.assertEqual(
            breakdown.reason_code,
            LatencyReasonCode.CAPTURE_TIMESTAMP_MISSING,
        )

    def test_compensation_is_bounded_by_time_and_prediction_horizon(self) -> None:
        compensator = LatencyCompensator(
            max_latency_ms=500.0,
            max_prediction_frames=5.0,
        )
        breakdown, compensation = compensator.evaluate(
            remote_timeline(),
            30.0,
            evaluated_at=mark(100_700.0, 1_650.0),
        )

        self.assertEqual(breakdown.end_to_end_ms, 700.0)
        self.assertAlmostEqual(compensation.applied_latency_ms, 500.0 / 3.0)
        self.assertAlmostEqual(compensation.frames_ahead, 5.0)
        self.assertTrue(compensation.clamped)
        self.assertEqual(
            compensation.reason_code, LatencyReasonCode.COMPENSATION_CLAMPED
        )


class TimestampedControlTests(unittest.TestCase):
    def test_control_recomputes_frame_age_at_publish_time(self) -> None:
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
            ),
            selected_global_vehicle_id=3,
            selected_local_track_id=4,
            target_velocity=(5.0, 0.0),
            source_fps=20.0,
            timestamps=remote_timeline(),
            identity_decision=None,
            reid_confidence_level="high",
        )

        decision = ControlPolicy().frame_command(
            frame_data,
            (360, 640, 3),
            sequence=9,
            now=1.100,
        )

        self.assertEqual(
            decision.payload["latency_breakdown"]["end_to_end_ms"], 150.0
        )
        self.assertEqual(
            decision.payload["latency_compensation"]["frames_ahead"], 3.0
        )
        self.assertEqual(decision.projected_target_center, (335.0, 180.0))
        self.assertEqual(decision.payload["frame_timestamps"]["frame_id"], 7)
        self.assertEqual(decision.payload["capture_timestamp_ms"], 100_000.0)


if __name__ == "__main__":
    unittest.main()
