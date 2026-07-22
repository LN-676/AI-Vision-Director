"""Qt-facing coordinator that invokes existing application use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal, Slot


@dataclass(frozen=True)
class VideoSyncPlan:
    frames_to_skip: int
    wait_seconds: float
    lag_ms: float


def video_sync_plan(
    *,
    start_frame: int,
    current_frame: int,
    source_fps: float,
    playback_speed: float,
    elapsed_seconds: float,
    max_skip: int = 120,
) -> VideoSyncPlan:
    """Keep media time tied to the source clock instead of inference speed."""

    fps = max(1.0, float(source_fps))
    speed = max(0.05, float(playback_speed))
    elapsed = max(0.0, float(elapsed_seconds))
    desired_frame = start_frame + int(elapsed * fps * speed)
    overdue_frames = max(0, desired_frame - current_frame)
    frames_to_skip = min(max(0, int(max_skip)), overdue_frames)
    next_frame = current_frame + frames_to_skip
    next_due_seconds = max(0.0, (next_frame - start_frame) / (fps * speed))
    wait_seconds = max(0.0, next_due_seconds - elapsed)
    lag_ms = overdue_frames * 1000.0 / fps
    return VideoSyncPlan(frames_to_skip, wait_seconds, lag_ms)


class QtRuntimeController(QObject):
    OVERLAY_FONT_HEIGHT = 80
    beforeFrameReady = Signal(object)
    afterFrameReady = Signal(object)
    statusChanged = Signal(str)
    fpsChanged = Signal(float)
    inferenceChanged = Signal(float)
    runningChanged = Signal(bool)
    vehiclesChanged = Signal(object)
    timelineChanged = Signal(int, int, float)
    metricsChanged = Signal(object)

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
        self.skipped_frames = 0
        self.playback_speed = 1.0
        self._selected_detection = None
        self._frames_since_fps = 0
        self._fps_started = monotonic()
        self._display_fps = 0.0
        self._playback_started_at = monotonic()
        self._playback_start_frame = 0
        self._next_video_request_at = 0.0
        self._video_lag_ms = 0.0
        self._last_metrics_emit = 0.0
        self._last_received_count: int | None = None
        self._last_received_at = monotonic()
        self._observed_source_fps = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(min(5, max(1, int(config.update_interval_ms))))
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

    @Slot(float)
    def set_playback_speed(self, speed: float) -> None:
        self.playback_speed = max(0.05, float(speed))
        self._reset_playback_clock()
        self.statusChanged.emit(f"Playback speed: {self.playback_speed:g}×")

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
                get_skipped_frames=lambda: self.skipped_frames,
                should_render_preview=lambda: True,
                get_frame_timing=self.dependencies.tracking_server.latest_frame_timing,
            )
            self.running = True
            self.skipped_frames = 0
            self._last_received_count = None
            self._last_received_at = monotonic()
            self._observed_source_fps = 0.0
            self._reset_playback_clock()
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
        self._next_video_request_at = 0.0
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
            self._reset_playback_clock()
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

    def first_feature_preview(self, gid: int) -> bytes | None:
        return self.application.feature_gallery.first_feature_crop_jpeg(gid)

    def feature_snapshots(self, gid: int):
        return self.application.feature_gallery.feature_snapshots(gid, "master")

    def vehicle_display_name(self, gid: int) -> str:
        return self.application.identity_store.display_label(gid)

    def rollback_features(self, gid: int, feature_ids: list[int]) -> int:
        result = self.application.feature_gallery.rollback_features(
            feature_ids,
            vehicle_id=gid,
            reason="manual contamination rollback from Qt feature manager",
            actor="desktop_qt",
        )
        self.refresh_vehicles()
        self.statusChanged.emit(
            f"Deleted {result.rolled_back_count} feature photo(s) from active ReID "
            f"matching for GID {gid}"
        )
        return result.rolled_back_count

    def close(self) -> None:
        self._timer.stop()
        self._metrics_timer.stop()
        self.running = False
        self.dependencies.tracking_server.publish_stop()
        self.dependencies.tracking_server.stop()
        self.application.close()

    @Slot()
    def _poll(self) -> None:
        now = monotonic()
        result = self.session.poll()
        if result is not None:
            if result.error is not None:
                self.running = False
                self.runningChanged.emit(False)
                self.statusChanged.emit(f"Tracking error: {result.error}")
                return
            if result.raw_frame is None or result.frame_data is None:
                if self.input_config.source_type == "iphone" and self.running:
                    self._next_video_request_at = now + 0.005
                    return
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
            self._update_fps()
            self._update_observed_source_fps(result.frame_data, now)
            self._synchronize_video_clock(now)
            frame_count = self.session.get_source_frame_count() or 0
            self.timelineChanged.emit(
                max(0, frame_count - 1),
                self.session.get_current_frame_index(),
                float(self.session.get_source_fps() or 0.0),
            )
            self._emit_metrics(now)
        if self.running and now >= self._next_video_request_at:
            self.session.request_frame()

    def _update_fps(self) -> None:
        self._frames_since_fps += 1
        elapsed = monotonic() - self._fps_started
        if elapsed >= 0.5:
            self._display_fps = self._frames_since_fps / elapsed
            self.fpsChanged.emit(self._display_fps)
            self._frames_since_fps = 0
            self._fps_started = monotonic()

    def _reset_playback_clock(self) -> None:
        self._playback_started_at = monotonic()
        self._playback_start_frame = self.session.get_current_frame_index()
        self._next_video_request_at = 0.0
        self._video_lag_ms = 0.0

    def _synchronize_video_clock(self, now: float) -> None:
        if self.input_config.source_type not in {"video_file", "video_url"}:
            self._next_video_request_at = 0.0
            self._video_lag_ms = 0.0
            return
        source_fps = self.session.get_source_fps()
        if not source_fps:
            self._next_video_request_at = 0.0
            return
        current_frame = self.session.get_current_frame_index()
        elapsed = max(0.0, now - self._playback_started_at)
        plan = video_sync_plan(
            start_frame=self._playback_start_frame,
            current_frame=current_frame,
            source_fps=source_fps,
            playback_speed=self.playback_speed,
            elapsed_seconds=elapsed,
        )
        if plan.frames_to_skip:
            skipped = self.session.skip(plan.frames_to_skip)
            self.skipped_frames += skipped
            current_frame = self.session.get_current_frame_index()
            plan = video_sync_plan(
                start_frame=self._playback_start_frame,
                current_frame=current_frame,
                source_fps=source_fps,
                playback_speed=self.playback_speed,
                elapsed_seconds=elapsed,
            )
        self._video_lag_ms = plan.lag_ms
        self._next_video_request_at = now + plan.wait_seconds

    def _emit_metrics(self, now: float) -> None:
        if self.last_frame_data is None or now - self._last_metrics_emit < 0.10:
            return
        self._last_metrics_emit = now
        frame_data = self.last_frame_data
        source_fps = (
            self._observed_source_fps
            if self.input_config.source_type == "iphone" and self._observed_source_fps > 0.0
            else frame_data.source_fps or self.session.get_source_fps() or 0.0
        )
        counters = dict(frame_data.stream_counters or {})
        stream_drops = (
            int(counters.get("source_sequence_gaps", 0))
            + int(counters.get("receive_overwritten", 0))
            + int(counters.get("decode_failed", 0))
        )
        latency_breakdown = frame_data.latency_breakdown
        end_to_end_ms = (
            float(latency_breakdown.end_to_end_ms)
            if latency_breakdown is not None
            else 0.0
        )
        self.metricsChanged.emit(
            {
                "display_fps": self._display_fps,
                "source_fps": float(source_fps),
                "frame_index": self.session.get_current_frame_index(),
                "skipped_frames": self.skipped_frames + stream_drops,
                "video_lag_ms": self._video_lag_ms,
                "inference_ms": float(frame_data.inference_time_ms),
                "pipeline_ms": float(frame_data.pipeline_time_ms),
                "receive_ms": float(frame_data.receive_latency_ms or 0.0),
                "decode_ms": float(frame_data.decode_time_ms),
                "end_to_end_ms": end_to_end_ms,
            }
        )

    def _update_observed_source_fps(self, frame_data, now: float) -> None:
        if self.input_config.source_type != "iphone":
            return
        received = int((frame_data.stream_counters or {}).get("received", 0))
        if self._last_received_count is not None:
            elapsed = max(0.001, now - self._last_received_at)
            delta = max(0, received - self._last_received_count)
            instant_fps = delta / elapsed
            if 0.0 < instant_fps < 240.0:
                self._observed_source_fps = (
                    instant_fps
                    if self._observed_source_fps <= 0.0
                    else self._observed_source_fps * 0.75 + instant_fps * 0.25
                )
        self._last_received_count = received
        self._last_received_at = now

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
            global_id = self.application.identity_manager.global_id_for_detection(detection)
            label = f"LID {detection.track_id}"
            if global_id is not None:
                label += f"  GID {global_id}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            thickness = 5
            scale = cv2.getFontScaleFromHeight(
                font, self.OVERLAY_FONT_HEIGHT, thickness
            )
            (_text_width, text_height), baseline = cv2.getTextSize(
                label, font, scale, thickness
            )
            text_y = y1 - 12
            if text_y - text_height < 0:
                text_y = min(annotated.shape[0] - baseline - 4, y1 + text_height + 12)
            cv2.putText(
                annotated,
                label,
                (max(0, x1), max(text_height, text_y)),
                font,
                scale,
                (0, 0, 0),
                thickness + 5,
                cv2.LINE_AA,
            )
            cv2.putText(
                annotated,
                label,
                (max(0, x1), max(text_height, text_y)),
                font,
                scale,
                color,
                thickness,
                cv2.LINE_AA,
            )
        return annotated
