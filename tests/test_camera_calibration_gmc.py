from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from autocamtracker.vision.camera_calibration import (
    CameraCalibration,
    CameraCalibrationStore,
    CameraCalibrationSubsystem,
)
from autocamtracker.vision.gmc import (
    GMCBackendResult,
    GMCConfig,
    GMCMeasurement,
    GMCReasonCode,
    GlobalMotionCompensator,
)
from autocamtracker.core.pipeline_processor import PipelineProcessor
from autocamtracker.tracking.detection_store import DetectionStore
from autocamtracker.tracking.identity_manager import GlobalIdentityManager
from autocamtracker.vision.reframer import Reframer
from autocamtracker.vision.framing_engine import FramingEngine


def calibration(profile_id: str = "iphone-main") -> CameraCalibration:
    return CameraCalibration(
        profile_id=profile_id,
        camera_name="iPhone main",
        image_width=1920,
        image_height=1080,
        fx=1500.0,
        fy=1480.0,
        cx=960.0,
        cy=540.0,
        distortion_coefficients=(-0.1, 0.03, 0.0, 0.0, 0.0),
        rms_reprojection_error=0.22,
        calibrated_at=100.0,
        calibration_views=12,
    )


class FakeCalibrationBackend:
    def __init__(self) -> None:
        self.calibrate_kwargs = None
        self.undistort_calls = []

    def calibrate_chessboard(self, frames, **kwargs):
        self.calibrate_kwargs = kwargs
        self.frame_count = len(list(frames))
        return calibration(kwargs["profile_id"])

    def undistort(self, frame, profile):
        self.undistort_calls.append((frame, profile.profile_id))
        return frame


class FakeGMCBackend:
    def __init__(self, result: GMCBackendResult) -> None:
        self.result = result
        self.calls = []

    def estimate(self, previous, current, previous_exclusions, current_exclusions, config):
        self.calls.append((
            previous, current, previous_exclusions, current_exclusions, config
        ))
        return self.result


class CameraCalibrationTests(unittest.TestCase):
    def test_rejects_incomplete_distortion_model(self) -> None:
        with self.assertRaises(ValueError):
            CameraCalibration(
                profile_id="invalid",
                camera_name="camera",
                image_width=640,
                image_height=480,
                fx=500.0,
                fy=500.0,
                cx=320.0,
                cy=240.0,
                distortion_coefficients=(0.0, 0.0, 0.0),
                rms_reprojection_error=0.0,
                calibrated_at=1.0,
                calibration_views=1,
            )

    def test_intrinsics_scale_with_frame_resolution(self) -> None:
        scaled = calibration().scaled_to(960, 540)

        self.assertEqual((scaled.fx, scaled.fy), (750.0, 740.0))
        self.assertEqual((scaled.cx, scaled.cy), (480.0, 270.0))
        self.assertEqual(scaled.distortion_coefficients, calibration().distortion_coefficients)

    def test_store_round_trips_versioned_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "calibrations.json"
            store = CameraCalibrationStore(path)
            store.save(calibration())
            store.save(calibration("webcam-0"))

            self.assertEqual(
                [item.profile_id for item in store.list_profiles()],
                ["iphone-main", "webcam-0"],
            )
            self.assertEqual(store.get("iphone-main"), calibration())
            self.assertTrue(store.delete("webcam-0"))
            self.assertFalse(store.delete("missing"))

    def test_subsystem_calibrates_persists_activates_and_undistorts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = FakeCalibrationBackend()
            subsystem = CameraCalibrationSubsystem(
                CameraCalibrationStore(Path(temp_dir) / "calibrations.json"), backend
            )
            result = subsystem.calibrate_chessboard(
                ["one", "two"],
                profile_id="iphone-main",
                camera_name="iPhone main",
                board_size=(9, 6),
                square_size=0.024,
                min_views=2,
            )
            subsystem.activate(result.profile_id)
            frame = SimpleNamespace(shape=(1080, 1920, 3))

            output, profile_id = subsystem.undistort(frame)

            self.assertIs(output, frame)
            self.assertEqual(profile_id, "iphone-main")
            self.assertEqual(backend.frame_count, 2)
            self.assertEqual(backend.undistort_calls[0][1], "iphone-main")


class GlobalMotionCompensatorTests(unittest.TestCase):
    def test_rejects_invalid_configuration_and_measurement(self) -> None:
        with self.assertRaises(ValueError):
            GMCConfig(min_inlier_ratio=1.1)
        with self.assertRaises(ValueError):
            GMCMeasurement((1.0, 0.0, 0.0, 0.0, 1.0, 0.0), 5, 6, 0.0)

    def test_estimates_motion_excludes_foreground_and_inverts_transform(self) -> None:
        measurement = GMCMeasurement((1.0, 0.0, 10.0, 0.0, 1.0, -4.0), 50, 40, 0.4)
        backend = FakeGMCBackend(GMCBackendResult(measurement, GMCReasonCode.ESTIMATED))
        gmc = GlobalMotionCompensator(backend=backend)
        first = SimpleNamespace(shape=(360, 640, 3), name="first")
        second = SimpleNamespace(shape=(360, 640, 3), name="second")
        first_box = (10.0, 20.0, 80.0, 90.0)
        second_box = (20.0, 16.0, 90.0, 86.0)

        initial = gmc.update(first, [first_box])
        estimate = gmc.update(second, [second_box])

        self.assertEqual(initial.reason_code, GMCReasonCode.INITIALIZING)
        self.assertTrue(estimate.reliable)
        self.assertEqual(estimate.reason_code, GMCReasonCode.ESTIMATED)
        self.assertEqual((estimate.translation_x, estimate.translation_y), (10.0, -4.0))
        self.assertEqual(estimate.inlier_ratio, 0.8)
        compensated = estimate.compensate_point((10.0, -4.0))
        self.assertAlmostEqual(compensated[0], 0.0)
        self.assertAlmostEqual(compensated[1], 0.0)
        self.assertEqual(backend.calls[0][2], (first_box,))
        self.assertEqual(backend.calls[0][3], (second_box,))

    def test_large_frames_use_smaller_analysis_pixels_and_restore_source_coordinates(self) -> None:
        import numpy as np

        measurement = GMCMeasurement((1.0, 0.0, 5.0, 0.0, 1.0, -2.0), 40, 36, 0.5)
        backend = FakeGMCBackend(GMCBackendResult(measurement, GMCReasonCode.ESTIMATED))
        gmc = GlobalMotionCompensator(
            GMCConfig(analysis_max_dimension=960),
            backend=backend,
        )
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        box = (200.0, 100.0, 600.0, 500.0)

        gmc.update(frame, [box])
        estimate = gmc.update(frame, [box])

        previous, current, previous_boxes, current_boxes, _config = backend.calls[0]
        self.assertEqual(previous.shape[:2], (540, 960))
        self.assertEqual(current.shape[:2], (540, 960))
        self.assertEqual(previous_boxes, ((100.0, 50.0, 300.0, 250.0),))
        self.assertEqual(current_boxes, previous_boxes)
        self.assertEqual((estimate.translation_x, estimate.translation_y), (10.0, -4.0))
        self.assertEqual(estimate.residual_px, 1.0)

    def test_rejects_low_inlier_and_excessive_motion(self) -> None:
        low = GMCMeasurement((1.0, 0.0, 2.0, 0.0, 1.0, 1.0), 50, 10, 1.0)
        low_backend = FakeGMCBackend(GMCBackendResult(low, GMCReasonCode.ESTIMATED))
        frame = SimpleNamespace(shape=(100, 100, 3))
        low_gmc = GlobalMotionCompensator(backend=low_backend)
        low_gmc.update(frame)
        low_estimate = low_gmc.update(frame)

        excessive = GMCMeasurement((1.0, 0.0, 40.0, 0.0, 1.0, 0.0), 50, 45, 0.5)
        excessive_backend = FakeGMCBackend(
            GMCBackendResult(excessive, GMCReasonCode.ESTIMATED)
        )
        excessive_gmc = GlobalMotionCompensator(
            GMCConfig(max_translation_ratio=0.10), backend=excessive_backend
        )
        excessive_gmc.update(frame)
        excessive_estimate = excessive_gmc.update(frame)

        self.assertFalse(low_estimate.reliable)
        self.assertEqual(low_estimate.reason_code, GMCReasonCode.LOW_INLIER_RATIO)
        self.assertFalse(excessive_estimate.reliable)
        self.assertEqual(
            excessive_estimate.reason_code, GMCReasonCode.EXCESSIVE_TRANSFORM
        )

    def test_camera_cut_and_shape_change_reset_temporal_pairing(self) -> None:
        measurement = GMCMeasurement((1.0, 0.0, 0.0, 0.0, 1.0, 0.0), 30, 30, 0.0)
        backend = FakeGMCBackend(GMCBackendResult(measurement, GMCReasonCode.ESTIMATED))
        gmc = GlobalMotionCompensator(backend=backend)
        frame = SimpleNamespace(shape=(100, 200, 3))
        changed = SimpleNamespace(shape=(200, 200, 3))
        gmc.update(frame)

        shape_result = gmc.update(changed)
        gmc.reset(GMCReasonCode.CAMERA_CUT_RESET)
        cut_result = gmc.update(changed)

        self.assertEqual(shape_result.reason_code, GMCReasonCode.FRAME_SHAPE_CHANGED)
        self.assertEqual(cut_result.reason_code, GMCReasonCode.CAMERA_CUT_RESET)
        self.assertEqual(len(backend.calls), 0)

    def test_active_calibration_is_applied_before_gmc(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calibration_backend = FakeCalibrationBackend()
            calibration_subsystem = CameraCalibrationSubsystem(
                CameraCalibrationStore(Path(temp_dir) / "calibrations.json"),
                calibration_backend,
            )
            calibration_subsystem.store.save(calibration())
            calibration_subsystem.activate("iphone-main")
            gmc_backend = FakeGMCBackend(GMCBackendResult(
                GMCMeasurement((1.0, 0.0, 0.0, 0.0, 1.0, 0.0), 30, 30, 0.0),
                GMCReasonCode.ESTIMATED,
            ))
            gmc = GlobalMotionCompensator(
                backend=gmc_backend, calibration=calibration_subsystem
            )
            frame = SimpleNamespace(shape=(1080, 1920, 3))

            first = gmc.update(frame)
            second = gmc.update(frame)

            self.assertEqual(first.calibration_profile_id, "iphone-main")
            self.assertEqual(second.calibration_profile_id, "iphone-main")
            self.assertEqual(len(calibration_backend.undistort_calls), 2)

    def test_pipeline_publishes_gmc_and_resets_it_on_scene_cut(self) -> None:
        class SceneCuts:
            def __init__(self) -> None:
                self.values = iter([False, True])

            def update(self, frame):
                return next(self.values)

            def reset(self):
                pass

        class RecordingGMC:
            def __init__(self) -> None:
                self.resets = []
                self.exclusions = []

            def update(self, frame, exclusions):
                self.exclusions.append(exclusions)
                return SimpleNamespace(calibration_profile_id=None)

            def reset(self, reason=GMCReasonCode.INITIALIZING):
                self.resets.append(reason)

        gmc = RecordingGMC()
        pipeline = PipelineProcessor(
            DetectionStore(),
            GlobalIdentityManager(),
            SceneCuts(),  # type: ignore[arg-type]
            Reframer(engine=FramingEngine()),
            gmc=gmc,  # type: ignore[arg-type]
        )
        frame = SimpleNamespace(shape=(360, 640, 3))
        candidate = SimpleNamespace(bbox=(1.0, 2.0, 11.0, 12.0))

        first = pipeline.process(
            frame,
            [],
            lambda image, detections: image,
            render_preview=False,
        )
        tracker_resets = []
        second = pipeline.process(
            frame,
            [candidate],  # type: ignore[list-item]
            lambda image, detections: image,
            reset_tracker_state=lambda: tracker_resets.append(True),
            render_preview=False,
        )

        self.assertIsNotNone(first.global_motion)
        self.assertIsNotNone(second.global_motion)
        self.assertIsNotNone(first.timestamps)
        self.assertIsNotNone(first.latency_breakdown)
        self.assertIsNotNone(first.latency_compensation)
        self.assertEqual(gmc.resets, [GMCReasonCode.CAMERA_CUT_RESET])
        self.assertEqual(gmc.exclusions, [[], []])
        self.assertEqual(tracker_resets, [True])


if __name__ == "__main__":
    unittest.main()
