from dataclasses import FrozenInstanceError
import unittest

from autocamtracker.domain import (
    BoundingBox,
    CameraCommand,
    Detection,
    DetectionBatch,
    FramePacket,
    IdentityState,
    TargetState,
    Track,
    TrackBatch,
)


class DomainContractTests(unittest.TestCase):
    def test_frame_detection_and_track_batches_share_frame_identity(self) -> None:
        frame = FramePacket(
            frame_index=7,
            timestamp=12.5,
            source_id="iphone",
            image=object(),
            width=1920,
            height=1080,
            source_fps=30.0,
        )
        bbox = BoundingBox(10.0, 20.0, 110.0, 220.0)
        detection = Detection(bbox, class_id=2, class_name="car", confidence=0.91)
        detections = DetectionBatch(
            frame_index=frame.frame_index,
            timestamp=frame.timestamp,
            detections=(detection,),
            model_name="yolo26n.pt",
            inference_time_ms=8.2,
        )
        track = Track(
            local_track_id=42,
            bbox=bbox,
            class_id=2,
            class_name="car",
            confidence=0.91,
        )
        tracks = TrackBatch(
            frame_index=detections.frame_index,
            timestamp=detections.timestamp,
            tracks=(track,),
            tracker_name="bytetrack",
        )

        self.assertEqual(tracks.frame_index, 7)
        self.assertEqual(tracks.tracks[0].local_track_id, 42)
        self.assertEqual(tracks.tracks[0].bbox.center, (60.0, 120.0))

    def test_track_contract_preserves_detection_without_local_id(self) -> None:
        track = Track(
            local_track_id=None,
            bbox=BoundingBox(1.0, 2.0, 3.0, 4.0),
            class_id=2,
            class_name="car",
            confidence=0.75,
        )

        self.assertIsNone(track.local_track_id)

    def test_identity_and_target_keep_gid_and_lid_distinct(self) -> None:
        bbox = BoundingBox(100.0, 200.0, 300.0, 400.0)
        identity = IdentityState(
            global_identity_id=5,
            local_track_id=17,
            status="tracking",
            class_name="car",
            confidence=0.88,
            bbox=bbox,
            reid_score=0.93,
        )
        target = TargetState(
            status="coasting",
            global_identity_id=identity.global_identity_id,
            local_track_id=identity.local_track_id,
            bbox=bbox,
            confidence=0.8,
            lost_frames=2,
            velocity=(4.0, -1.5),
            predicted=True,
        )

        self.assertEqual(target.global_identity_id, 5)
        self.assertEqual(target.local_track_id, 17)
        self.assertEqual(target.center, (200.0, 300.0))

    def test_camera_command_uses_normalized_errors(self) -> None:
        command = CameraCommand(
            sequence=9,
            timestamp_ms=1234,
            target_locked=True,
            target_id=5,
            error_x=-0.25,
            error_y=0.5,
            confidence=0.9,
            zoom_factor=1.6,
        )

        self.assertEqual(command.target_id, 5)
        with self.assertRaises(ValueError):
            CameraCommand(
                sequence=10,
                timestamp_ms=1235,
                target_locked=True,
                error_x=1.1,
            )

    def test_contracts_are_frozen_snapshots(self) -> None:
        bbox = BoundingBox(0.0, 0.0, 10.0, 10.0)

        with self.assertRaises(FrozenInstanceError):
            bbox.left = 1.0  # type: ignore[misc]

    def test_invalid_confidence_is_rejected_at_the_boundary(self) -> None:
        with self.assertRaises(ValueError):
            Detection(
                bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
                class_id=2,
                class_name="car",
                confidence=1.01,
            )

    def test_batches_copy_iterables_to_immutable_tuples(self) -> None:
        detection = Detection(
            bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
            class_id=2,
            class_name="car",
            confidence=0.9,
        )
        source = [detection]
        batch = DetectionBatch(1, 1.0, source)  # type: ignore[arg-type]
        source.clear()

        self.assertEqual(batch.detections, (detection,))

    def test_unknown_state_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TargetState(status="paused")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
