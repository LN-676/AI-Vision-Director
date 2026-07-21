import json
from pathlib import Path
import tempfile
import unittest

from autocamtracker.evaluation import GIDLossBenchmarkRunner, GIDObservation
from autocamtracker.evaluation.gid_loss import (
    REQUIRED_SCENARIOS,
    evaluate_gid_loss,
    load_gid_loss_spec,
)
from autocamtracker.evaluation.offline_replay import load_replay_jsonl


class GIDLossBenchmarkTests(unittest.TestCase):
    def test_manifest_defines_all_phase_10_loss_scenarios(self) -> None:
        benchmark = load_gid_loss_spec(Path("evaluation/gid_loss_scenarios.json"))

        self.assertEqual(
            tuple(scenario.scenario_id for scenario in benchmark.scenarios),
            REQUIRED_SCENARIOS,
        )
        self.assertEqual(benchmark.version, 2)
        self.assertEqual(benchmark.dataset_version, "phase-10-v1")
        self.assertIn("gid_lock_rate_min", benchmark.metrics)
        self.assertEqual(benchmark.summary()["scenario_count"], 14)

    def test_metrics_measure_loss_switch_reacquire_and_motor_safety(self) -> None:
        expected = 7
        observations = [
            GIDObservation(expected, expected),
            GIDObservation(expected, None),
            GIDObservation(expected, 9, motor_safe=False),
            GIDObservation(expected, expected),
            GIDObservation(expected, None, target_visible=False),
            GIDObservation(expected, expected),
        ]

        metrics = evaluate_gid_loss(observations)

        self.assertEqual(metrics.visible_frame_count, 5)
        self.assertEqual(metrics.locked_frame_count, 3)
        self.assertEqual(metrics.gid_lock_rate, 0.6)
        self.assertEqual(metrics.max_consecutive_lost_frames, 2)
        self.assertEqual(metrics.id_switches, 1)
        self.assertEqual(metrics.reacquire_events, 2)
        self.assertEqual(metrics.median_reacquire_frames, 1.0)
        self.assertEqual(metrics.motor_unsafe_frames, 1)

    def test_runner_reports_each_scenario_and_threshold_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            replay_root = root / "replays"
            replay_root.mkdir()
            scenarios = []
            for scenario_id in REQUIRED_SCENARIOS:
                assigned = 99 if scenario_id == "same_color" else 7
                record = {
                    "frame_index": 0,
                    "capture_timestamp_ms": 0,
                    "output": {
                        "gid": {
                            "expected_identity_id": 7,
                            "assigned_identity_id": assigned,
                            "target_visible": True,
                            "motor_safe": True,
                        }
                    },
                }
                (replay_root / f"{scenario_id}.jsonl").write_text(
                    json.dumps(record) + "\n", encoding="utf-8"
                )
                scenarios.append({
                    "id": scenario_id,
                    "name": scenario_id,
                    "replay": f"{scenario_id}.jsonl",
                    "minimum_frames": 1,
                })
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "version": 2,
                "dataset_version": "test-v1",
                "replay_root": "replays",
                "thresholds": {
                    "gid_lock_rate_min": 0.9,
                    "max_consecutive_lost_frames": 12,
                    "id_switches_max": 0,
                    "median_reacquire_frames_max": 8,
                    "motor_unsafe_frames_max": 0,
                },
                "scenarios": scenarios,
            }), encoding="utf-8")

            report = GIDLossBenchmarkRunner(load_gid_loss_spec(manifest)).run()

        self.assertFalse(report.passed)
        self.assertEqual(len(report.scenarios), 14)
        failed = next(item for item in report.scenarios if item.scenario_id == "same_color")
        self.assertEqual(failed.failures, ("gid_lock_rate", "id_switches"))

    def test_manifest_rejects_an_incomplete_scenario_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "manifest.json"
            manifest.write_text(json.dumps({
                "version": 2,
                "dataset_version": "bad",
                "replay_root": "replays",
                "thresholds": {},
                "scenarios": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid GID loss scenario set"):
                load_gid_loss_spec(manifest)

    def test_gid_annotation_requires_explicit_safety_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            replay = Path(temp_dir) / "incomplete.jsonl"
            replay.write_text(json.dumps({
                "frame_index": 0,
                "capture_timestamp_ms": 0,
                "output": {
                    "gid": {
                        "expected_identity_id": 7,
                        "assigned_identity_id": 7,
                    }
                },
            }) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid replay JSONL record"):
                load_replay_jsonl(replay)


if __name__ == "__main__":
    unittest.main()
