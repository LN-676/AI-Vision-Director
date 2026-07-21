from pathlib import Path
from types import SimpleNamespace
import unittest

from autocamtracker.server.camera_stream_receiver import CameraStreamReceiver
from autocamtracker.server.control_policy import ControlPolicy
from autocamtracker.server.control_publisher import ControlPublisher
from autocamtracker.server.protocol import decode_message, encode_message, tracking_message
from autocamtracker.server.transport import WebSocketTransport
from autocamtracker.server.websocket_server import TrackingWebSocketServer
from autocamtracker.tracking.identity_components import (
    IdentityDecision,
    IdentityReasonCode,
)


class WebSocketComponentTests(unittest.TestCase):
    def test_facade_composes_all_phase_eight_components(self) -> None:
        server = TrackingWebSocketServer()
        self.assertIsInstance(server.transport, WebSocketTransport)
        self.assertIsInstance(server.camera_stream_receiver, CameraStreamReceiver)
        self.assertIsInstance(server.control_policy, ControlPolicy)
        self.assertIsInstance(server.control_publisher, ControlPublisher)

    def test_protocol_round_trip_is_domain_independent(self) -> None:
        payload = tracking_message(target_locked=True, error_x=0.25, sequence=7)
        self.assertEqual(decode_message(encode_message(payload)), payload)

    def test_control_policy_does_not_mutate_cv_frame_state(self) -> None:
        original_projection = (11.0, 22.0)
        frame_data = SimpleNamespace(
            selected_targets=[SimpleNamespace(
                confidence=0.9,
                status="tracking",
                lost_frame_count=0,
                center=(320.0, 180.0),
                bbox=(280.0, 140.0, 360.0, 220.0),
            )],
            tracking_status="tracking",
            framing_status=SimpleNamespace(error_x=0.0, error_y=0.0, framing_mode="medium"),
            selected_global_vehicle_id=3,
            selected_local_track_id=4,
            target_velocity=(5.0, 0.0),
            latency_compensation_ms=50.0,
            source_fps=30.0,
            projected_target_center=original_projection,
            identity_decision=IdentityDecision(
                IdentityReasonCode.CURRENT_TRACK_MATCH,
                True,
                "tracker_continuity",
                1.0,
                {"tracker_match": 1.0, "detection_confidence": 0.9},
                4,
            ),
        )

        decision = ControlPolicy().frame_command(frame_data, (360, 640, 3), sequence=8)

        self.assertTrue(decision.payload["target_locked"])
        self.assertNotEqual(decision.projected_target_center, original_projection)
        self.assertEqual(frame_data.projected_target_center, original_projection)
        self.assertEqual(decision.payload["identity_reason_code"], "CURRENT_TRACK_MATCH")
        self.assertEqual(decision.payload["identity_sub_scores"]["tracker_match"], 1.0)

    def test_control_publisher_sequences_without_transport_dependency(self) -> None:
        sent = []
        publisher = ControlPublisher(sent.append)
        publisher.publish_test_pulse()
        publisher.publish_stop()
        publisher.publish_control("request_state")
        self.assertEqual([item["type"] for item in sent], ["tracking", "tracking", "control"])
        self.assertEqual([sent[0]["sequence"], sent[1]["sequence"]], [1, 2])

    def test_transport_source_has_no_cv_domain_dependencies_or_state(self) -> None:
        path = Path(__file__).resolve().parents[1] / "src" / "autocamtracker" / "server" / "transport.py"
        source = path.read_text(encoding="utf-8")
        forbidden = (
            "autocamtracker.core",
            "autocamtracker.domain",
            "autocamtracker.tracking",
            "autocamtracker.vision",
            "frame_data",
            "selected_targets",
            "tracking_status",
            "projected_target_center",
        )
        self.assertEqual([token for token in forbidden if token in source], [])


if __name__ == "__main__":
    unittest.main()
