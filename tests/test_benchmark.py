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
)
from autocamtracker.evaluation.benchmark import (
    MAX_SCORE,
    load_results,
    result_from_report,
    save_results,
)
from autocamtracker.evaluation.live_capture import LiveBenchmarkRecorder
from autocamtracker.evaluation.standard_formats import (
    export_coco,
    export_mot_challenge,
)
from autocamtracker.evaluation.vision_benchmark import (
    VisionBenchmarkRequest,
    VisionBenchmarkRunner,
)
from autocamtracker.vision.types import TrackedDetection


def item(*, identity_id=7, track_id=None):
    return EvaluationObject(
        bbox=(0.0, 0.0, 100.0, 60.0),
        class_id=2,
        confidence=0.95,
        identity_id=identity_id,
        track_id=track_id,
    )


class BenchmarkTests(unittest.TestCase):
    def _report(self):
        frames = []
        for index in range(3):
            output = ReplayOutput(
                detections=(item(identity_id=None, track_id=11),),
                command_timestamp_ms=index * 100.0 + 20.0,
                reid=ReIDObservation(7, (7,), True, 7),
                control=ControlObservation(
                    timestamp_ms=index * 100.0,
                    error_x=0.01,
                    error_y=0.01,
                    command_x=0.01,
                    command_y=0.01,
                    target_in_frame=True,
                ),
            )
            frames.append(
                ReplayFrame(
                    index,
                    index * 100.0,
                    (item(),),
                    recorded_output=output,
                )
            )
        return OfflineReplayRunner().run(frames), frames

    def test_full_report_produces_covered_score_and_round_trips(self) -> None:
        report, _ = self._report()
        result = result_from_report(
            report,
            model_path="/models/yolo.pt",
            tracker="botsort",
            dataset_version="golden-v1",
        )

        self.assertEqual(result.score.coverage, 1.0)
        self.assertGreater(result.score.total, 0)
        self.assertLessEqual(result.score.total, MAX_SCORE)
        self.assertIn("MRR", result.metrics)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "results.json"
            save_results(path, [result])
            loaded = load_results(path)
        self.assertEqual(loaded, [result])

    def test_standard_exports_use_coco_and_mot_shapes(self) -> None:
        _, frames = self._report()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            coco_gt = root / "gt.json"
            coco_predictions = root / "predictions.json"
            mot_gt = root / "gt.txt"
            mot_predictions = root / "predictions.txt"
            export_coco(
                frames,
                ground_truth_path=coco_gt,
                predictions_path=coco_predictions,
            )
            export_mot_challenge(
                frames,
                ground_truth_path=mot_gt,
                predictions_path=mot_predictions,
            )
            self.assertIn('"annotations"', coco_gt.read_text(encoding="utf-8"))
            self.assertTrue(mot_gt.read_text(encoding="utf-8").startswith("1,7,"))
            self.assertTrue(
                mot_predictions.read_text(encoding="utf-8").startswith("1,11,")
            )

    def test_live_capture_manifest_marks_ground_truth_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = LiveBenchmarkRecorder(temp_dir)
            session = recorder.start(
                source="iphone",
                model_path="/models/yolo.pt",
                tracker="botsort",
            )
            stopped = recorder.stop()
            manifest = (session / "manifest.json").read_text(encoding="utf-8")

        self.assertEqual(stopped, session)
        self.assertIn('"ground_truth_status": "pending"', manifest)

    def test_vision_runner_executes_models_sequentially(self) -> None:
        events = []

        class FakeDetector:
            def __init__(self, config):
                self.config = config
                self.index = 0
                events.append(("created", Path(config.model_path).name))

            def load_model(self):
                events.append(("loaded", Path(self.config.model_path).name))

            def open_source(self):
                self.index = 0

            def read_frame(self):
                if self.index >= 2:
                    return None
                self.index += 1
                return object()

            def track_frame(self, _frame):
                return [
                    TrackedDetection(
                        track_id=11,
                        bbox=(0.0, 0.0, 100.0, 60.0),
                        class_id=2,
                        class_name="car",
                        confidence=0.95,
                        center=(50.0, 30.0),
                        frame_index=self.index - 1,
                        timestamp=0.0,
                        tracker_name="botsort",
                    )
                ]

            def seek_video_frame(self, frame_index):
                self.index = frame_index
                return True

            def close(self):
                events.append(("closed", Path(self.config.model_path).name))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "golden.mp4"
            video.touch()
            models = (root / "a.pt", root / "b.pt")
            for model in models:
                model.touch()
            annotations = root / "annotations.jsonl"
            annotations.write_text(
                '{"frame_index":0,"capture_timestamp_ms":0,"ground_truth":'
                '[{"bbox":[0,0,100,60],"class_id":2,"identity_id":7}]}\n'
                '{"frame_index":1,"capture_timestamp_ms":33.3,"ground_truth":'
                '[{"bbox":[0,0,100,60],"class_id":2,"identity_id":7}]}\n',
                encoding="utf-8",
            )
            results = VisionBenchmarkRunner(FakeDetector).run(
                VisionBenchmarkRequest(
                    video_path=video,
                    annotation_path=annotations,
                    model_paths=models,
                    warmup_frames=1,
                )
            )

        self.assertEqual([item.model_name for item in results], ["a", "b"])
        self.assertEqual(
            [event for event in events if event[0] == "loaded"],
            [("loaded", "a.pt"), ("loaded", "b.pt")],
        )
        self.assertTrue(all(item.score.profile == "Vision Core" for item in results))


if __name__ == "__main__":
    unittest.main()
