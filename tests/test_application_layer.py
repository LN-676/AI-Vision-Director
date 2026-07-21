from pathlib import Path
from types import SimpleNamespace
import unittest

from autocamtracker.application import InputConfig, TrackingSession


class FakeReframer:
    def __init__(self) -> None:
        self.mode = None
        self.config = SimpleNamespace(output_width=0, output_height=0)

    def set_framing_mode(self, mode: str) -> None:
        self.mode = mode


class FakePipeline:
    def __init__(self) -> None:
        self.reframer = FakeReframer()
        self.calls = []
        self.reset_count = 0

    def process(self, **kwargs):
        self.calls.append(kwargs)
        return {"frame": kwargs["frame"], "detections": kwargs["detections"]}

    def reset(self) -> None:
        self.reset_count += 1


class FakeDetector:
    instances = []

    def __init__(self, config, frame_provider=None) -> None:
        self.config = config
        self.frame_provider = frame_provider
        self.loaded = False
        self.opened = False
        self.closed = False
        self.close_clear_cache = None
        self.reset_count = 0
        self.frame_index = 0
        FakeDetector.instances.append(self)

    def load_model(self) -> None:
        self.loaded = True

    def open_source(self) -> None:
        self.opened = True

    def close(self, clear_temp_cache=False) -> None:
        self.closed = True
        self.close_clear_cache = clear_temp_cache

    def read_and_track(self):
        self.frame_index += 1
        return f"frame-{self.frame_index}", [f"detection-{self.frame_index}"]

    def get_source_fps(self):
        return 30.0

    def get_source_frame_count(self):
        return 300

    def get_current_frame_index(self):
        return self.frame_index

    def seek_video_frame(self, frame_index):
        self.frame_index = frame_index
        return True

    def skip_video_frames(self, frame_count):
        self.frame_index += frame_count
        return frame_count

    def reset_tracker_state(self):
        self.reset_count += 1


class FakeWorker:
    instances = []

    def __init__(self, detector, pipeline, *callbacks) -> None:
        self.detector = detector
        self.pipeline = pipeline
        self.callbacks = callbacks
        self.closed = False
        self.discard_count = 0
        self.request_count = 0
        FakeWorker.instances.append(self)

    def request_frame(self):
        self.request_count += 1
        return True

    def poll(self):
        return "result"

    def discard_results(self):
        self.discard_count += 1

    def run_locked(self, callback):
        return callback()

    def close(self):
        self.closed = True


class TrackingSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeDetector.instances.clear()
        FakeWorker.instances.clear()
        self.pipeline = FakePipeline()
        self.session = TrackingSession(
            self.pipeline,  # type: ignore[arg-type]
            detector_factory=FakeDetector,
            worker_factory=FakeWorker,
        )
        self.callbacks = {
            "frame_provider": lambda: None,
            "draw_detections": lambda frame, _detections: frame,
            "get_skipped_frames": lambda: 0,
            "should_render_preview": lambda: True,
            "get_frame_timing": lambda: {},
        }

    def test_start_resume_and_stop_own_detector_worker_lifecycle(self) -> None:
        config = InputConfig(source_type="iphone", model_path="yolo26n.pt")

        resumed = self.session.start(config, **self.callbacks)
        first_detector = FakeDetector.instances[0]
        first_worker = FakeWorker.instances[0]
        resumed_again = self.session.start(config, **self.callbacks)

        self.assertFalse(resumed)
        self.assertTrue(resumed_again)
        self.assertTrue(first_detector.loaded)
        self.assertTrue(first_detector.opened)
        self.assertEqual(len(FakeDetector.instances), 1)
        self.assertTrue(first_worker.closed)
        self.assertEqual(len(FakeWorker.instances), 2)
        self.assertTrue(self.session.request_frame())
        self.assertEqual(self.session.poll(), "result")

        self.session.stop()

        self.assertTrue(first_detector.closed)
        self.assertFalse(self.session.has_source)
        self.assertFalse(self.session.has_worker)

    def test_changed_configuration_replaces_source(self) -> None:
        first = InputConfig(source_type="iphone", tracker_name="bytetrack")
        second = InputConfig(source_type="iphone", tracker_name="botsort")
        self.session.start(first, **self.callbacks)
        old_detector = FakeDetector.instances[0]

        resumed = self.session.start(second, **self.callbacks)

        self.assertFalse(resumed)
        self.assertTrue(old_detector.closed)
        self.assertEqual(len(FakeDetector.instances), 2)

    def test_synchronous_frame_use_case_hides_pipeline_and_locking(self) -> None:
        self.session.start(InputConfig(source_type="iphone"), **self.callbacks)

        frame, frame_data = self.session.process_next_frame(
            draw_detections=self.callbacks["draw_detections"],
            inference_time_ms=4.5,
            skipped_frames=2,
        )

        self.assertEqual(frame, "frame-1")
        self.assertEqual(frame_data["detections"], ["detection-1"])
        self.assertEqual(self.pipeline.calls[0]["source_fps"], 30.0)
        self.assertEqual(self.pipeline.calls[0]["inference_time_ms"], 4.5)

    def test_playback_and_framing_use_cases_do_not_expose_detector(self) -> None:
        self.session.start(InputConfig(source_type="video_file"), **self.callbacks)

        self.assertTrue(self.session.seek(40))
        self.assertEqual(self.session.skip(3), 3)
        self.assertEqual(self.session.get_current_frame_index(), 43)
        self.session.set_framing_mode("close")
        self.session.set_output_size(1920, 1080)
        self.session.reset_pipeline()

        self.assertEqual(self.pipeline.reframer.mode, "close")
        self.assertEqual(self.pipeline.reframer.config.output_width, 1920)
        self.assertEqual(self.pipeline.reset_count, 1)


class ApplicationDependencyTests(unittest.TestCase):
    def test_tkinter_layer_does_not_import_cv_runtime_or_worker(self) -> None:
        ui_root = Path(__file__).resolve().parents[1] / "src" / "autocamtracker" / "ui"
        combined = "\n".join(path.read_text(encoding="utf-8") for path in ui_root.rglob("*.py"))

        self.assertNotIn("autocamtracker.vision.detector import", combined)
        self.assertNotIn("autocamtracker.core.pipeline_processor import", combined)
        self.assertNotIn("autocamtracker.core.pipeline_worker import", combined)


if __name__ == "__main__":
    unittest.main()
