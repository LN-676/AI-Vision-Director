from __future__ import annotations

from types import SimpleNamespace
import unittest

from autocamtracker.core.frame_data import FrameData
from autocamtracker.core.performance_evaluation import (
    ConfusionMatrixStats,
    PerformanceEvaluationTracker,
    mean_average_precision,
)
from autocamtracker.core.timestamps import FrameTimeline, TimestampMark, TimestampStage


class PerformanceEvaluationTests(unittest.TestCase):
    def test_confusion_matrix_calculates_precision_recall_and_accuracy(self) -> None:
        stats = ConfusionMatrixStats(true_positive=8, false_positive=2, false_negative=4, true_negative=6)

        self.assertAlmostEqual(stats.precision, 0.8)
        self.assertAlmostEqual(stats.recall, 8 / 12)
        self.assertAlmostEqual(stats.accuracy, 0.7)

    def test_confusion_matrix_returns_none_when_denominator_is_missing(self) -> None:
        stats = ConfusionMatrixStats()

        self.assertIsNone(stats.precision)
        self.assertIsNone(stats.recall)
        self.assertIsNone(stats.accuracy)

    def test_mean_average_precision_clamps_samples(self) -> None:
        self.assertAlmostEqual(mean_average_precision([0.8, 1.2, -0.5]), 0.6)
        self.assertIsNone(mean_average_precision([]))

    def test_tracker_records_runtime_snapshot_and_id_switches(self) -> None:
        tracker = PerformanceEvaluationTracker(window_size=4)
        tracker.record_frame(self._frame(24.0, selected_lid=7, confidence=0.9))
        tracker.record_frame(self._frame(30.0, selected_lid=7, confidence=0.8))
        snapshot = tracker.record_frame(self._frame(18.0, selected_lid=9, confidence=0.7, locked=False))

        self.assertEqual(snapshot.frame_count, 3)
        self.assertAlmostEqual(snapshot.average_fps, 24.0)
        self.assertAlmostEqual(snapshot.average_confidence, 0.8)
        self.assertAlmostEqual(snapshot.tracking_stability, 2 / 3)
        self.assertEqual(snapshot.id_switches, 1)
        self.assertEqual(snapshot.detection_count, 2)
        self.assertEqual(snapshot.candidate_count, 1)

    def test_tracker_reports_stage_drops_and_loss_episode_frames(self) -> None:
        tracker = PerformanceEvaluationTracker(window_size=10)
        tracker.record_frame(self._frame(30.0, selected_lid=7, confidence=0.9, timestamp_ms=1_000))
        tracker.record_frame(
            self._frame(
                30.0,
                selected_lid=7,
                confidence=0.2,
                locked=False,
                timestamp_ms=2_000,
                source_frame_id=10,
                stream_counters={
                    "source_sequence_gaps": 2,
                    "receive_overwritten": 3,
                    "decode_failed": 1,
                },
            )
        )
        snapshot = tracker.record_frame(
            self._frame(
                30.0,
                selected_lid=7,
                confidence=0.8,
                timestamp_ms=3_000,
                source_frame_id=11,
                stream_counters={
                    "source_sequence_gaps": 2,
                    "receive_overwritten": 3,
                    "decode_failed": 1,
                },
            )
        )

        self.assertEqual(snapshot.total_dropped_frames, 7)
        self.assertEqual(snapshot.completed_loss_episodes, 1)
        self.assertAlmostEqual(snapshot.longest_loss_seconds, 1.0)
        episode = tracker.loss_episodes()[0]
        self.assertEqual((episode.start_frame_id, episode.end_frame_id), (10, 11))
        self.assertEqual(episode.reason_code, "TRACK_NOT_LOCKED")

    @staticmethod
    def _frame(
        fps: float,
        *,
        selected_lid: int,
        confidence: float,
        locked: bool = True,
        timestamp_ms: float | None = None,
        source_frame_id: int | None = None,
        stream_counters: dict[str, int] | None = None,
    ) -> FrameData:
        target = SimpleNamespace(
            confidence=confidence,
            lost_frame_count=0 if locked else 2,
            status="tracking" if locked else "lost",
        )
        timeline = None
        if timestamp_ms is not None:
            mark = TimestampMark(timestamp_ms, timestamp_ms)
            timeline = FrameTimeline.local(source_frame_id or 0, "test", mark)
            timeline.mark(TimestampStage.PIPELINE_COMPLETED, mark)
        return FrameData(
            raw_frame=None,
            before_frame=None,
            after_frame=None,
            detections=[SimpleNamespace(), SimpleNamespace()],
            candidates=[SimpleNamespace()],
            selected_targets=[target],
            framing_status=SimpleNamespace(crop_window=(0, 0, 1, 1), error_x=0.0, error_y=0.0),
            tracking_status="tracking",
            selected_local_track_id=selected_lid,
            display_fps=fps,
            source_fps=30.0,
            inference_time_ms=12.0,
            pipeline_time_ms=16.0,
            skipped_frames=1,
            timestamps=timeline,
            source_frame_id=source_frame_id,
            stream_counters=stream_counters or {},
        )


if __name__ == "__main__":
    unittest.main()
