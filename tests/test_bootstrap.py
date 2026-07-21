from pathlib import Path
import ast
import tempfile
import unittest

from autocamtracker.bootstrap import bootstrap
from autocamtracker.ui.app import AppConfig


class FakeRoot:
    def __init__(self) -> None:
        self.mainloop_count = 0

    def mainloop(self) -> None:
        self.mainloop_count += 1


class FakeApp:
    def __init__(self, root, config, dependencies) -> None:
        self.root = root
        self.config = config
        self.dependencies = dependencies
        self.input_config = dependencies.application.input_config


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_constructs_and_injects_complete_desktop_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root_path = Path(temp_dir)
            config = AppConfig(
                telemetry_dir=root_path / "telemetry",
                identity_db_path=root_path / "identity.sqlite3",
            )

            desktop = bootstrap(
                config=config,
                argv=["sample.mp4"],
                root_factory=FakeRoot,
                app_factory=FakeApp,
            )
            try:
                dependencies = desktop.app.dependencies
                self.assertIs(desktop.app.root, desktop.root)
                self.assertIs(dependencies.application.tracking_session.pipeline, dependencies.application.pipeline)
                self.assertIs(dependencies.tracking_server.telemetry_logger, dependencies.telemetry_logger)
                self.assertEqual(desktop.app.input_config.source_type, "video_file")
                self.assertEqual(desktop.app.input_config.video_path, "sample.mp4")

                dependencies.tracking_server.on_status("connected")
                dependencies.tracking_server.on_control({"type": "control"})
                self.assertEqual(dependencies.iphone_status_queue.get_nowait(), "connected")
                self.assertEqual(
                    dependencies.iphone_control_queue.get_nowait(), {"type": "control"}
                )

                desktop.run()
                self.assertEqual(desktop.root.mainloop_count, 1)
            finally:
                dependencies.application.close()

    def test_bootstrap_is_the_only_production_composition_root(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src" / "autocamtracker"
        constructors = {
            "TrackingApplication",
            "TelemetryLogger",
            "PerformanceEvaluationTracker",
            "TrackingWebSocketServer",
            "TrackShotController",
            "IdentitySessionLinks",
            "AutoCamTrackerApp",
            "DetectionStore",
            "VehicleIdentityStore",
            "FeatureGallery",
            "GlobalIdentityManager",
            "AutoFeatureSampler",
            "SceneCutDetector",
            "FramingConfig",
            "Reframer",
            "PipelineProcessor",
            "TrackingSession",
        }
        diagnostic_exceptions = {
            ("core/self_test.py", "DetectionStore"),
            ("core/self_test.py", "VehicleIdentityStore"),
            ("core/self_test.py", "FeatureGallery"),
            ("core/self_test.py", "GlobalIdentityManager"),
            ("core/self_test.py", "AutoFeatureSampler"),
            ("vision/reframer.py", "FramingConfig"),
        }
        offenders = []
        for path in source_root.rglob("*.py"):
            if path.name == "bootstrap.py":
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id in constructors:
                    relative_path = str(path.relative_to(source_root))
                    if (relative_path, node.func.id) in diagnostic_exceptions:
                        continue
                    offenders.append(
                        f"{relative_path}:{node.lineno}: {node.func.id}"
                    )

        self.assertEqual(offenders, [])

    def test_main_is_only_a_bootstrap_adapter(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "src" / "autocamtracker" / "main.py"
        text = main_path.read_text(encoding="utf-8")

        self.assertIn("from autocamtracker.bootstrap import run", text)
        self.assertNotIn("tkinter", text)
        self.assertNotIn("AutoCamTrackerApp", text)


if __name__ == "__main__":
    unittest.main()
