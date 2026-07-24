from pathlib import Path
import tempfile
from types import SimpleNamespace
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
from autocamtracker.evaluation.auto_benchmark import (
    AutoBenchmarkRequest,
    AutoBenchmarkRunner,
    BenchmarkCancelled,
    BenchmarkModelPair,
    BenchmarkRunControl,
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

    def test_quick_auto_runner_enrolls_then_averages_three_rounds(self) -> None:
        class FakeDetector:
            def __init__(self, config):
                self.config = config
                self.index = 0

            def load_model(self):
                pass

            def open_source(self):
                self.index = 0

            def get_source_fps(self):
                return 5.0

            def read_frame(self):
                if self.index >= 12:
                    return None
                self.index += 1
                return object()

            def track_frame(self, _frame):
                return [
                    TrackedDetection(
                        track_id=1 if self.index < 8 else 2,
                        bbox=(0.0, 0.0, 100.0, 60.0),
                        class_id=2,
                        class_name="car",
                        confidence=0.9,
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
                pass

        class FakeEncoder:
            available = True
            error = None

            def __init__(self, _config):
                pass

            def extract_batch(self, _frame, bboxes):
                return [[1.0, 0.0] for _ in bboxes]

        class FakeCuts:
            def __init__(self):
                self.count = 0

            def update(self, _frame):
                self.count += 1
                return self.count == 4

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "source.mp4"
            detection = root / "detector.pt"
            reid = root / "reid.onnx"
            for path in (video, detection, reid):
                path.touch()
            request = AutoBenchmarkRequest(
                video_path=video,
                model_pairs=(BenchmarkModelPair(detection, reid),),
                rounds=3,
                feature_limit=2,
                warmup_frames=1,
            )
            progress_updates = []
            result = AutoBenchmarkRunner(
                detector_factory=FakeDetector,
                embedding_factory=FakeEncoder,
                scene_cut_factory=FakeCuts,
                quality_assessor=SimpleNamespace(
                    assess=lambda *_: SimpleNamespace(accepted=True)
                ),
            ).run(
                request,
                progress=lambda current, total, text: progress_updates.append(
                    (current, total, text)
                ),
            )[0]
            output = root / "quick-auto.json"
            save_results(output, [result])
            reloaded = load_results(output)[0]

        self.assertEqual(result.model_name, "detector + reid")
        self.assertEqual(reloaded, result)
        self.assertEqual(result.metrics["Feature count"], 2)
        self.assertEqual(result.metrics["Rounds"], 3)
        self.assertEqual(result.score.profile, "Quick Auto · proxy")
        self.assertAlmostEqual(result.score.coverage, 4 / 6)
        self.assertGreaterEqual(len(result.metadata["shots"]), 2)
        self.assertEqual(progress_updates[-1], (4_000, 4_000, "Complete"))
        self.assertTrue(
            any(
                0 < current < total and "features" in text
                for current, total, text in progress_updates
            )
        )

    def test_quick_auto_run_control_pauses_resumes_and_cancels(self) -> None:
        control = BenchmarkRunControl()

        control.pause()
        self.assertTrue(control.paused)
        control.resume()
        self.assertFalse(control.paused)
        control.checkpoint()

        control.cancel()
        self.assertTrue(control.cancelled)
        with self.assertRaises(BenchmarkCancelled):
            control.checkpoint()


if __name__ == "__main__":
    unittest.main()
