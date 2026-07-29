from types import SimpleNamespace
import unittest

from autocamtracker.core.track_shot_plan import TrackShotController
from autocamtracker.ui_qt.controller import QtRuntimeController


class _TrackingServer:
    def __init__(self, *, motor_ready: bool = True) -> None:
        self.motor_ready = motor_ready
        self.frames = []
        self.stop_count = 0

    def publish_frame(self, frame_data, frame_shape) -> None:
        self.frames.append((frame_data, frame_shape))

    def publish_stop(self) -> None:
        self.stop_count += 1


def _frame_data(*, locked: bool = True):
    targets = []
    if locked:
        targets.append(
            SimpleNamespace(
                center=(320.0, 180.0),
                status="tracking",
                lost_frame_count=0,
            )
        )
    return SimpleNamespace(
        tracking_status="tracking" if locked else "idle",
        selected_targets=targets,
    )


class QtMotorOutputTests(unittest.TestCase):
    frame_shape = (360, 640, 3)

    def _controller(self, *, armed: bool, motor_ready: bool = True):
        server = _TrackingServer(motor_ready=motor_ready)
        controller = SimpleNamespace(
            input_config=SimpleNamespace(source_type="iphone"),
            dependencies=SimpleNamespace(
                tracking_server=server,
                track_shot_controller=TrackShotController(),
            ),
            _motor_tracking_armed=armed,
            _motor_output_was_active=False,
        )
        return controller, server

    def test_armed_qt_iphone_target_publishes_tracking_frame(self) -> None:
        controller, server = self._controller(armed=True)

        QtRuntimeController._publish_tracking_output(
            controller, _frame_data(), self.frame_shape
        )

        self.assertEqual(len(server.frames), 1)
        self.assertEqual(server.stop_count, 0)
        self.assertTrue(controller._motor_output_was_active)

    def test_unarmed_or_unready_qt_output_remains_stopped(self) -> None:
        for armed, ready in ((False, True), (True, False)):
            with self.subTest(armed=armed, ready=ready):
                controller, server = self._controller(
                    armed=armed, motor_ready=ready
                )
                QtRuntimeController._publish_tracking_output(
                    controller, _frame_data(), self.frame_shape
                )
                self.assertEqual(server.frames, [])
                self.assertEqual(server.stop_count, 0)

    def test_target_loss_sends_one_stop_after_active_output(self) -> None:
        controller, server = self._controller(armed=True)
        QtRuntimeController._publish_tracking_output(
            controller, _frame_data(), self.frame_shape
        )

        QtRuntimeController._publish_tracking_output(
            controller, _frame_data(locked=False), self.frame_shape
        )
        QtRuntimeController._publish_tracking_output(
            controller, _frame_data(locked=False), self.frame_shape
        )

        self.assertEqual(server.stop_count, 1)
        self.assertFalse(controller._motor_output_was_active)


if __name__ == "__main__":
    unittest.main()
