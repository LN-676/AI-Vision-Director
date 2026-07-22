"""Qt-facing coordinator that invokes existing application use cases."""

from __future__ import annotations

from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal, Slot


class QtRuntimeController(QObject):
    beforeFrameReady = Signal(object)
    afterFrameReady = Signal(object)
    statusChanged = Signal(str)
    fpsChanged = Signal(float)
    inferenceChanged = Signal(float)
    runningChanged = Signal(bool)
    vehiclesChanged = Signal(object)
    timelineChanged = Signal(int, int)

    def __init__(self, config, dependencies, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.dependencies = dependencies
        self.application = dependencies.application
        self.session = self.application.tracking_session
        self.input_config = self.application.input_config
        default_model = config.model_dir / config.default_model
        if not Path(self.input_config.model_path).is_absolute():
            self.input_config.model_path = str(default_model)
        self.running = False
        self.recording = False
        self.last_raw_frame = None
        self.last_frame_data = None
        self.last_inference_ms = 0.0
        self._selected_detection = None
        self._frames_since_fps = 0
        self._fps_started = monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(config.update_interval_ms)))
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(500)
        self._metrics_timer.timeout.connect(self.refresh_vehicles)
        self._metrics_timer.start()

    @Slot(str)
    def configure_source(self, source: str) -> None:
        if source not in {"iphone", "webcam", "video_file", "video_url", "screen_region"}:
            return
        if self.session.has_source:
            self.stop()
        self.input_config.source_type = source
        self.statusChanged.emit(f"Source: {source}")

    @Slot(str)
    def set_video_file(self, path: str) -> None:
        self.input_config.video_path = path or None
        self.configure_source("video_file")

    @Slot(str)
    def set_video_url(self, url: str) -> None:
        self.input_config.video_url = url or None
        self.configure_source("video_url")

    @Slot(int)
    def set_camera_index(self, index: int) -> None:
        self.input_config.camera_index = int(index)

    @Slot(str)
    def set_screen_region(self, value: str) -> None:
        try:
            parts = tuple(int(part.strip()) for part in value.split(","))
            if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
                raise ValueError
        except ValueError:
            self.statusChanged.emit("Screen region must be left,top,width,height")
            return
        self.input_config.screen_region = parts
        self.configure_source("screen_region")

    @Slot(str, str, float)
    def configure_tracking(self, profile: str, tracker: str, confidence: float) -> None:
        model = "model/yolo26n.pt" if profile == "High FPS" else "model/yolo26s.pt"
        self.input_config.model_path = str(self.config.model_dir / model)
        self.input_config.tracker_name = "bytetrack" if tracker == "ByteTrack" else "botsort"
        self.input_config.confidence_threshold = float(confidence)
        self.input_config.tracker_reid_enabled = profile == "Balanced ID"

    @Slot()
    def start(self) -> None:
        try:
            if self.input_config.source_type == "iphone":
                self.dependencies.tracking_server.start()
            provider = (
                self.dependencies.tracking_server.read_latest_frame
                if self.input_config.source_type == "iphone"
                else None
            )
            self.session.start(
                self.input_config,
                frame_provider=provider,
                draw_detections=self._draw_detections,
                get_skipped_frames=lambda: 0,
                should_render_preview=lambda: True,
                get_frame_timing=self.dependencies.tracking_server.latest_frame_timing,
            )
            self.running = True
            self.runningChanged.emit(True)
            self.statusChanged.emit("Tracking started")
            self.session.request_frame()
        except Exception as exc:
            self.running = False
            self.runningChanged.emit(False)
            self.statusChanged.emit(f"Start failed: {exc}")

    @Slot()
    def pause(self) -> None:
        self.running = False
        self.session.pause()
        self.dependencies.tracking_server.publish_stop()
        self.runningChanged.emit(False)
        self.statusChanged.emit("Tracking paused")

    @Slot()
    def stop(self) -> None:
        self.running = False
        self.dependencies.tracking_server.publish_stop()
        self.session.stop()
        self.application.identity_manager.reset()
        self._selected_detection = None
        self.runningChanged.emit(False)
        self.statusChanged.emit("Tracking stopped")

    @Slot()
    def toggle_recording(self) -> None:
        self.recording = not self.recording
        self.statusChanged.emit("Recording armed" if self.recording else "Recording stopped")

    @Slot(int)
    def seek(self, frame_index: int) -> None:
        if not self.session.has_source or self.input_config.source_type not in {"video_file", "video_url"}:
            return
        was_running = self.running
        self.running = False
        self.session.discard_results()
        if self.session.seek(frame_index):
            self.session.reset_pipeline()
            self.statusChanged.emit(f"Seek: frame {frame_index}")
        self.running = was_running

    @Slot(float, float)
    def select_at(self, x: float, y: float) -> None:
        if self.last_raw_frame is None:
            return
        candidate = self.application.store.get_candidate_at_point(
            x, y, self.last_raw_frame.shape
        )
        if candidate is None:
            self.statusChanged.emit("No tracked vehicle at clicked point")
            return
        detection = self._detection_for_track(candidate.track_id)
        if detection is None:
            self.statusChanged.emit("Selected vehicle is no longer visible")
            return
        self._selected_detection = detection
        self.application.identity_manager.select_detection(
            detection, self.last_raw_frame, persist=False
        )
        self.statusChanged.emit(f"Selected LID {detection.track_id}")

    @Slot()
    def auto_track(self) -> None:
        candidates = self.application.store.rank_candidates(
            getattr(self.last_raw_frame, "shape", None), strategy="stable"
        )
        if not candidates or self.last_raw_frame is None:
            self.statusChanged.emit("Auto Track found no visible vehicle")
            return
        detection = self._detection_for_track(candidates[0].track_id)
        if detection is not None:
            self._selected_detection = detection
            self.application.identity_manager.select_detection(
                detection, self.last_raw_frame, persist=False
            )
            self.statusChanged.emit(f"Auto Track selected LID {detection.track_id}")

    @Slot()
    def clear_selection(self) -> None:
        self.application.identity_manager.reset()
        self.application.auto_feature_sampler.stop()
        self._selected_detection = None
        self.statusChanged.emit("Selection cleared")

    @Slot()
    def reset_tracking(self) -> None:
        self.clear_selection()
        self.session.reset_pipeline()
        self.statusChanged.emit("Tracking reset")

    @Slot(str)
    def set_framing(self, mode: str) -> None:
        if mode in {"wide", "medium", "close"}:
            self.session.set_framing_mode(mode)
            self.statusChanged.emit(f"Framing: {mode}")

    @Slot(str)
    def set_track_shot_mode(self, mode: str) -> None:
        if mode == "Zone":
            mode = "In/Out Auto"
        try:
            self.dependencies.track_shot_controller.set_mode(mode)
            self.statusChanged.emit(f"Track Shot: {mode}")
        except ValueError as exc:
            self.statusChanged.emit(str(exc))

    @Slot()
    def rearm_track_shot(self) -> None:
        self.dependencies.track_shot_controller.rearm()
        self.statusChanged.emit("Track Shot rearmed")

    @Slot()
    def add_vehicle(self) -> None:
        detection = self._current_detection()
        if detection is None or self.last_raw_frame is None:
            self.statusChanged.emit("Select a visible BBox before Add")
            return
        gid = self.application.identity_store.create_vehicle(
            detection, {"created_manually": True}
        )
        self.application.identity_manager.link_detection(
            gid, detection, self.last_raw_frame
        )
        self.refresh_vehicles()
        self.statusChanged.emit(f"Added GID {gid}")

    @Slot(int)
    def link_vehicle(self, gid: int) -> None:
        detection = self._current_detection()
        if detection is None or self.last_raw_frame is None:
            self.statusChanged.emit("Select a visible BBox before Link")
            return
        identity = self.application.identity_manager.link_detection(
            gid, detection, self.last_raw_frame
        )
        self.refresh_vehicles()
        self.statusChanged.emit(
            f"Linked LID {detection.track_id} to GID {gid}"
            if identity is not None
            else f"GID {gid} no longer exists"
        )

    @Slot(int)
    def find_vehicle(self, gid: int) -> None:
        if self.last_raw_frame is None:
            self.statusChanged.emit("Find GID is waiting for a frame")
            return
        identity, score = self.application.identity_manager.select_stored_vehicle(
            gid,
            self.application.store.current_detections,
            self.last_raw_frame,
            min_score=self.application.identity_manager.auto_reid_min_score,
        )
        self.statusChanged.emit(
            f"Find GID {gid}: score {score:.2f}"
            if identity is not None
            else f"GID {gid} not found"
        )

    @Slot()
    def release_vehicle(self) -> None:
        self.clear_selection()
        self.dependencies.tracking_server.publish_stop()
        self.statusChanged.emit("GID tracking released")

    @Slot(int)
    def delete_vehicle(self, gid: int) -> None:
        if self.application.identity_store.delete_vehicle(gid):
            self.application.feature_gallery.delete_vehicle_features(gid)
            self.refresh_vehicles()
            self.statusChanged.emit(f"Deleted GID {gid}")

    @Slot()
    def add_manual_feature(self) -> None:
        gid = self.application.identity_manager.selected_global_vehicle_id
        detection = self._current_detection()
        if gid is None or detection is None or self.last_raw_frame is None:
            self.statusChanged.emit("Select and link a visible GID before Feature")
            return
        from autocamtracker.tracking.feature_models import GalleryWriteContext

        context = GalleryWriteContext.from_identity_manager(
            self.application.identity_manager, source="qt_manual_feature_add"
        )
        result = self.application.feature_gallery.add_master_feature(
            gid, detection, self.last_raw_frame, context=context
        )
        self.refresh_vehicles()
        self.statusChanged.emit(
            f"Added feature {result.feature_id} to GID {gid}"
            if result.accepted
            else f"Feature rejected: {result.reason}"
        )

    @Slot()
    def toggle_auto_feature(self) -> None:
        sampler = self.application.auto_feature_sampler
        if sampler.active_vehicle_id is not None:
            sampler.stop()
            self.statusChanged.emit("Auto Feature stopped")
            return
        gid = self.application.identity_manager.selected_global_vehicle_id
        detection = self._current_detection()
        if gid is None or detection is None or self.last_raw_frame is None:
            self.statusChanged.emit("Select and link a visible GID before Auto Feature")
            return
        result = sampler.start(gid, detection, self.last_raw_frame, self.application.store)
        self.statusChanged.emit(
            f"Auto Feature active for GID {gid}"
            if result.accepted
            else f"Auto Feature waiting: {result.reason}"
        )

    @Slot()
    def refresh_vehicles(self) -> None:
        feature_counts = self.application.feature_gallery.summary_by_vehicle()
        summary = self.application.identity_store.summary(feature_counts=feature_counts)
        self.vehiclesChanged.emit(summary.vehicles)

    def close(self) -> None:
        self._timer.stop()
        self._metrics_timer.stop()
        self.running = False
        self.dependencies.tracking_server.publish_stop()
        self.dependencies.tracking_server.stop()
        self.application.close()

    @Slot()
    def _poll(self) -> None:
        result = self.session.poll()
        if result is not None:
            if result.error is not None:
                self.running = False
                self.runningChanged.emit(False)
                self.statusChanged.emit(f"Tracking error: {result.error}")
                return
            if result.raw_frame is None or result.frame_data is None:
                self.running = False
                self.runningChanged.emit(False)
                self.statusChanged.emit("End of source")
                return
            self.last_raw_frame = result.raw_frame
            self.last_frame_data = result.frame_data
            self.last_inference_ms = result.inference_time_ms
            before = getattr(result.frame_data, "before_frame", result.raw_frame)
            after = getattr(result.frame_data, "after_frame", result.raw_frame)
            self.beforeFrameReady.emit(before)
            self.afterFrameReady.emit(after)
            self.inferenceChanged.emit(result.inference_time_ms)
            self.dependencies.performance_evaluator.record_frame(result.frame_data)
            frame_count = self.session.get_source_frame_count() or 0
            self.timelineChanged.emit(
                max(0, frame_count - 1), self.session.get_current_frame_index()
            )
            self._update_fps()
        if self.running:
            self.session.request_frame()

    def _update_fps(self) -> None:
        self._frames_since_fps += 1
        elapsed = monotonic() - self._fps_started
        if elapsed >= 0.5:
            self.fpsChanged.emit(self._frames_since_fps / elapsed)
            self._frames_since_fps = 0
            self._fps_started = monotonic()

    def _current_detection(self):
        if self._selected_detection is None:
            return None
        return self._detection_for_track(self._selected_detection.track_id)

    def _detection_for_track(self, track_id):
        return next(
            (
                detection
                for detection in self.application.store.current_detections
                if detection.track_id == track_id
            ),
            None,
        )

    def _draw_detections(self, frame, detections):
        import cv2

        annotated = frame.copy()
        for detection in detections:
            x1, y1, x2, y2 = (int(value) for value in detection.bbox)
            selected = self.application.identity_manager.is_selected_detection(detection)
            color = (0, 0, 255) if selected else (80, 220, 80)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 4 if selected else 2)
            cv2.putText(
                annotated,
                f"LID {detection.track_id}",
                (x1, max(18, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )
        return annotated
