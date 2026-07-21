from pathlib import Path
import tempfile
import unittest

from autocamtracker.evaluation import (
    ControlObservation,
    EvaluationObject,
    OfflineReplayRunner,
    ReIDObservation,
    ReplayFrame,
    ReplayOutput,
    load_replay_jsonl,
)


def item(*, identity_id: int = 1, track_id: int | None = None, confidence: float = 0.9):
    return EvaluationObject(
        bbox=(10.0, 10.0, 50.0, 50.0),
        class_id=2,
        confidence=confidence,
        identity_id=identity_id,
        track_id=track_id,
    )


class OfflineReplayRunnerTests(unittest.TestCase):
    def test_perfect_replay_reports_all_requested_metric_groups(self) -> None:
        frames = [
            ReplayFrame(
                frame_index=0,
                capture_timestamp_ms=0.0,
                ground_truth=(item(),),
                recorded_output=ReplayOutput(
                    detections=(item(track_id=7),),
                    command_timestamp_ms=20.0,
                    reid=ReIDObservation(1, (1, 3, 4), True, 1),
                    control=ControlObservation(0.0, 0.2, 0.0, 0.2, 0.0, True),
                ),
            ),
            ReplayFrame(
                frame_index=1,
                capture_timestamp_ms=100.0,
                ground_truth=(item(),),
                recorded_output=ReplayOutput(
                    detections=(item(track_id=7),),
                    command_timestamp_ms=130.0,
                    reid=ReIDObservation(1, (1, 5, 6), True, 1),
                    control=ControlObservation(100.0, 0.04, 0.0, 0.05, 0.0, True),
                ),
            ),
        ]

        report = OfflineReplayRunner().run(frames)

        self.assertEqual(report.detection.map50, 1.0)
        self.assertEqual(report.detection.map50_95, 1.0)
        self.assertEqual(report.detection.precision, 1.0)
        self.assertEqual(report.detection.recall, 1.0)
        self.assertEqual(report.tracking.hota, 1.0)
        self.assertEqual(report.tracking.idf1, 1.0)
        self.assertEqual(report.tracking.mota, 1.0)
        self.assertEqual(report.tracking.id_switches, 0)
        self.assertEqual(report.tracking.fragmentation, 0)
        self.assertEqual(report.reid.rank1, 1.0)
        self.assertEqual(report.reid.rank5, 1.0)
        self.assertEqual(report.reid.mean_average_precision, 1.0)
        self.assertEqual(report.reid.false_reacquire_rate, 0.0)
        self.assertEqual(report.reid.reacquire_success_rate, 1.0)
        self.assertEqual(report.system.fps, 10.0)
        self.assertEqual(report.system.latency_p50_ms, 25.0)
        self.assertAlmostEqual(report.system.latency_p95_ms, 29.5)
        self.assertAlmostEqual(report.system.latency_p99_ms, 29.9)
        self.assertEqual(report.system.dropped_frame_rate, 0.0)
        self.assertEqual(report.control.overshoot, 0.0)
        self.assertEqual(report.control.settling_time_ms, 100.0)
        self.assertAlmostEqual(report.control.jitter, 0.15)
        self.assertEqual(report.control.target_out_of_frame_ratio, 0.0)
        self.assertEqual(report.to_dict()["Detection"]["mAP50-95"], 1.0)
        self.assertEqual(report.to_dict()["Tracking"]["HOTA"], 1.0)

    def test_tracking_counts_switch_and_fragmentation(self) -> None:
        frames = [
            ReplayFrame(0, 0.0, (item(),), recorded_output=ReplayOutput((item(track_id=10),), 10.0)),
            ReplayFrame(1, 100.0, (item(),), recorded_output=ReplayOutput((), 110.0)),
            ReplayFrame(2, 200.0, (item(),), recorded_output=ReplayOutput((item(track_id=11),), 210.0)),
        ]

        report = OfflineReplayRunner().run(frames)

        self.assertAlmostEqual(report.detection.recall, 2 / 3)
        self.assertAlmostEqual(report.tracking.idf1, 0.4)
        self.assertAlmostEqual(report.tracking.mota, 1 / 3)
        self.assertEqual(report.tracking.id_switches, 1)
        self.assertEqual(report.tracking.fragmentation, 1)

    def test_reid_and_control_failure_metrics(self) -> None:
        outputs = [
            ReplayOutput(
                detections=(item(track_id=2),),
                command_timestamp_ms=10.0,
                reid=ReIDObservation(1, (2, 3, 4, 5, 1), True, 2),
                control=ControlObservation(0.0, 0.5, 0.0, 0.4, 0.0, True),
            ),
            ReplayOutput(
                detections=(item(track_id=2),),
                command_timestamp_ms=110.0,
                reid=ReIDObservation(1, (8, 7, 6), True, None),
                control=ControlObservation(100.0, -0.1, 0.0, -0.2, 0.0, False),
            ),
        ]
        frames = [ReplayFrame(index, index * 100.0, (item(),), recorded_output=output)
                  for index, output in enumerate(outputs)]

        report = OfflineReplayRunner().run(frames)

        self.assertEqual(report.reid.rank1, 0.0)
        self.assertEqual(report.reid.rank5, 0.5)
        self.assertEqual(report.reid.mean_average_precision, 0.1)
        self.assertEqual(report.reid.false_reacquire_rate, 0.5)
        self.assertEqual(report.reid.reacquire_success_rate, 0.0)
        self.assertAlmostEqual(report.control.overshoot, 0.2)
        self.assertEqual(report.control.target_out_of_frame_ratio, 0.5)

    def test_dropped_frame_is_counted_without_processor_call(self) -> None:
        calls = []

        def processor(frame: ReplayFrame) -> ReplayOutput:
            calls.append(frame.frame_index)
            return ReplayOutput((item(track_id=1),), frame.capture_timestamp_ms + 5.0)

        report = OfflineReplayRunner(processor).run([
            ReplayFrame(0, 0.0, (item(),)),
            ReplayFrame(1, 100.0, (item(),), dropped=True),
        ])

        self.assertEqual(calls, [0])
        self.assertEqual(report.processed_frame_count, 1)
        self.assertEqual(report.dropped_frame_count, 1)
        self.assertEqual(report.system.dropped_frame_rate, 0.5)
        self.assertEqual(report.detection.recall, 0.5)

    def test_jsonl_loader_supports_recorded_outputs(self) -> None:
        record = (
            '{"frame_index":0,"capture_timestamp_ms":1000,"ground_truth":'
            '[{"bbox":[0,0,10,10],"class_id":2,"identity_id":1}],"output":'
            '{"detections":[{"bbox":[0,0,10,10],"class_id":2,"track_id":9}],'
            '"command_timestamp_ms":1012}}\n'
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "replay.jsonl"
            path.write_text(record, encoding="utf-8")
            frames = load_replay_jsonl(path)
            report = OfflineReplayRunner().run(frames)

        self.assertEqual(report.frame_count, 1)
        self.assertEqual(report.detection.map50, 1.0)
        self.assertEqual(report.system.latency_p50_ms, 12.0)


if __name__ == "__main__":
    unittest.main()
