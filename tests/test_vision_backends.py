from pathlib import Path
from types import SimpleNamespace
import unittest

from autocamtracker.tracking.backend import (
    DeepOcSortTrackerBackend,
    UltralyticsTrackerBackend,
)
from autocamtracker.tracking.tracker_adapter import TrackerOutputDetection
from autocamtracker.vision.detector import InputConfig, TrackedDetection, VideoDetector
from autocamtracker.vision.detector_backend import UltralyticsDetectorBackend
from autocamtracker.vision.frame_source import ConfiguredFrameSource


class FakeFrameSource:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.index = 0

    def open(self) -> None:
        self.opened = True

    def read(self):
        self.index += 1
        return "frame"

    def close(self) -> None:
        self.closed = True
        self.index = 0

    def get_fps(self):
        return 24.0

    def get_frame_count(self):
        return 120

    def get_frame_index(self):
        return self.index

    def seek(self, frame_index: int):
        self.index = frame_index
        return True

    def skip(self, frame_count: int):
        self.index += frame_count
        return frame_count


class FakeDetectorBackend:
    def __init__(self) -> None:
        self.model = object()
        self.loaded = False
        self.native_calls = []
        self.prediction_results = []
        self.native_results = []
        self.reset_count = 0

    def load(self) -> None:
        self.loaded = True

    def detect(self, frame):
        self.prediction_frame = frame
        return self.prediction_results

    def track_with_native_backend(self, frame, tracker_config):
        self.native_calls.append((frame, tracker_config))
        return self.native_results

    def reset_native_trackers(self) -> None:
        self.reset_count += 1


class FakeTrackerBackend:
    config_path = None
    adapter = None

    def __init__(self) -> None:
        self.initialized = False
        self.configured_fps = None
        self.track_calls = []
        self.reset_count = 0

    def initialize(self) -> None:
        self.initialized = True

    def configure(self, source_fps):
        self.configured_fps = source_fps

    def track(self, frame, frame_index):
        self.track_calls.append((frame, frame_index))
        return [
            TrackedDetection(
                track_id=7,
                bbox=(1.0, 2.0, 11.0, 22.0),
                class_id=2,
                class_name="car",
                confidence=0.9,
                center=(6.0, 12.0),
                frame_index=frame_index,
                timestamp=1.0,
                tracker_name="bytetrack",
            )
        ]

    def reset(self) -> None:
        self.reset_count += 1


def native_result():
    boxes = SimpleNamespace(
        xyxy=[[10.0, 20.0, 110.0, 220.0], [0.0, 0.0, 5.0, 5.0]],
        cls=[2, 0],
        conf=[0.91, 0.99],
        id=[42, 99],
    )
    return SimpleNamespace(names={0: "person", 2: "car"}, boxes=boxes)


class VisionBackendSplitTests(unittest.TestCase):
    def test_video_detector_coordinates_injected_boundaries(self) -> None:
        source = FakeFrameSource()
        detector_backend = FakeDetectorBackend()
        tracker_backend = FakeTrackerBackend()
        detector = VideoDetector(
            InputConfig(source_type="iphone", tracker_name="bytetrack"),
            frame_source=source,
            detector_backend=detector_backend,
            tracker_backend=tracker_backend,
        )

        detector.load_model()
        detector.open_source()
        frame, detections = detector.read_and_track()
        detector.reset_tracker_state()
        detector.close()

        self.assertTrue(detector_backend.loaded)
        self.assertTrue(tracker_backend.initialized)
        self.assertEqual(tracker_backend.configured_fps, 24.0)
        self.assertEqual(tracker_backend.track_calls, [("frame", 1)])
        self.assertEqual(frame, "frame")
        self.assertEqual(detections[0].track_id, 7)
        self.assertEqual(tracker_backend.reset_count, 1)
        self.assertTrue(source.closed)

    def test_default_composition_exposes_three_backends(self) -> None:
        detector = VideoDetector(
            InputConfig(source_type="iphone", tracker_name="bytetrack"),
            frame_provider=lambda: None,
        )

        self.assertIsInstance(detector.frame_source, ConfiguredFrameSource)
        self.assertIsInstance(detector.detector_backend, UltralyticsDetectorBackend)
        self.assertIsInstance(detector.tracker_backend, UltralyticsTrackerBackend)

    def test_native_tracker_preserves_v177_track_call_and_filtering(self) -> None:
        config = InputConfig(tracker_name="bytetrack", confidence_threshold=0.2)
        detector_backend = FakeDetectorBackend()
        detector_backend.native_results = [native_result()]
        tracker = UltralyticsTrackerBackend(config, detector_backend)
        tracker.configure(30.0)

        detections = tracker.track("pixels", frame_index=8)

        self.assertEqual(detector_backend.native_calls[0][0], "pixels")
        self.assertEqual(Path(detector_backend.native_calls[0][1]), tracker.config_path)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].track_id, 42)
        self.assertEqual(detections[0].bbox, (10.0, 20.0, 110.0, 220.0))
        self.assertEqual(detections[0].center, (60.0, 120.0))
        self.assertEqual(detections[0].frame_index, 8)

    def test_deepocsort_backend_preserves_predict_then_adapter_path(self) -> None:
        config = InputConfig(tracker_name="deepocsort", confidence_threshold=0.2)
        detector_backend = FakeDetectorBackend()
        detector_backend.prediction_results = [native_result()]
        tracker = DeepOcSortTrackerBackend(config, detector_backend)

        class FakeAdapter:
            def __init__(self) -> None:
                self.inputs = None

            def update(self, detections):
                self.inputs = detections
                return [
                    TrackerOutputDetection(
                        track_id=4,
                        bbox=detections[0].bbox,
                        class_id=detections[0].class_id,
                        class_name=detections[0].class_name,
                        confidence=detections[0].confidence,
                    )
                ]

            def reset(self) -> None:
                pass

        adapter = FakeAdapter()
        tracker._adapter = adapter  # type: ignore[assignment]

        detections = tracker.track("pixels", frame_index=3)

        self.assertEqual(detector_backend.prediction_frame, "pixels")
        self.assertEqual(len(adapter.inputs), 1)
        self.assertEqual(adapter.inputs[0].class_name, "car")
        self.assertEqual(detections[0].track_id, 4)
        self.assertEqual(detections[0].tracker_name, "deepocsort")

    def test_iphone_frame_source_keeps_v177_frame_index_semantics(self) -> None:
        frames = iter([None, "frame"])
        source = ConfiguredFrameSource(
            InputConfig(source_type="iphone", target_source_fps=30.0),
            frame_provider=lambda: next(frames),
        )

        source.open()

        self.assertEqual(source.get_fps(), 30.0)
        self.assertIsNone(source.read())
        self.assertEqual(source.get_frame_index(), 0)
        self.assertEqual(source.read(), "frame")
        self.assertEqual(source.get_frame_index(), 1)


if __name__ == "__main__":
    unittest.main()
