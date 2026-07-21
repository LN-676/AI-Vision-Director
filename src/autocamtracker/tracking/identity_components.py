"""Composable identity-management policies extracted from the legacy GID manager."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from autocamtracker.vision.detector import TrackedDetection


class IdentityLifecycleState(str, Enum):
    """Canonical lifecycle states for the selected global identity."""

    LOCKED = "LOCKED"
    COASTING = "COASTING"
    SEARCHING = "SEARCHING"
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    LOST = "LOST"


class IdentityStateMachine:
    """Owns the canonical identity lifecycle independently of UI status strings."""

    def __init__(self) -> None:
        self.state: IdentityLifecycleState | None = None
        self.previous_state: IdentityLifecycleState | None = None

    def transition(self, state: IdentityLifecycleState) -> IdentityLifecycleState:
        if state != self.state:
            self.previous_state = self.state
            self.state = state
        return state

    def reset(self) -> None:
        self.previous_state = self.state
        self.state = None


class IdentityMatcher:
    """Matches detections using the unchanged v1.0-alpha.1 color/size/motion score."""

    def __init__(self, min_score: float = 0.62, margin: float = 0.08, confirm_frames: int = 2) -> None:
        self.min_score = min_score
        self.margin = margin
        self.confirm_frames = confirm_frames
        self._pending_key: int | None = None
        self._pending_count = 0

    def reset_pending(self) -> None:
        self._pending_key = None
        self._pending_count = 0

    @staticmethod
    def find_current_track(identity: Any, detections: Iterable[TrackedDetection]) -> TrackedDetection | None:
        if identity is None or identity.last_track_id is None:
            return None
        return next((item for item in detections if item.track_id == identity.last_track_id), None)

    def color_signature(self, frame, bbox: tuple[float, float, float, float]):
        import cv2

        x1, y1, x2, y2 = self._clamp_bbox(bbox, frame.shape[1], frame.shape[0])
        if x2 - x1 <= 1 or y2 - y1 <= 1:
            return None
        crop = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        return hist.flatten().astype("float32")

    def choose(self, identity: Any, detections: list[TrackedDetection], frame) -> tuple[TrackedDetection | None, float]:
        if not detections:
            self.reset_pending()
            return None, 0.0
        scored = [(self._score(identity, detection, frame), detection) for detection in detections]
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        if best_score < self.min_score or best_score - second_score < self.margin:
            self.reset_pending()
            return None, best_score
        pending_key = best.track_id if best.track_id is not None else best.frame_index
        if pending_key == self._pending_key:
            self._pending_count += 1
        else:
            self._pending_key = pending_key
            self._pending_count = 1
        if self._pending_count >= self.confirm_frames:
            self.reset_pending()
            return best, best_score
        return None, best_score

    def _score(self, identity: Any, detection: TrackedDetection, frame) -> float:
        tracker_match = 1.0 if detection.track_id is not None and detection.track_id == identity.last_track_id else 0.0
        color = self._color_similarity(identity, detection, frame)
        size = self._size_similarity(identity.last_bbox, detection.bbox)
        motion = self._motion_similarity(identity.last_center, detection.center, frame.shape[1], frame.shape[0])
        confidence = max(0.0, min(1.0, detection.confidence))
        class_match = 1.0 if detection.class_name == identity.class_name else 0.0
        return 0.34 * tracker_match + 0.24 * color + 0.14 * size + 0.12 * motion + 0.10 * confidence + 0.06 * class_match

    def _color_similarity(self, identity: Any, detection: TrackedDetection, frame) -> float:
        import cv2

        if identity.color_signature is None:
            return 0.0
        signature = self.color_signature(frame, detection.bbox)
        if signature is None:
            return 0.0
        score = cv2.compareHist(identity.color_signature, signature, cv2.HISTCMP_CORREL)
        return float(max(0.0, min(1.0, score)))

    @staticmethod
    def _size_similarity(first, second) -> float:
        first_w, first_h = max(1.0, first[2] - first[0]), max(1.0, first[3] - first[1])
        second_w, second_h = max(1.0, second[2] - second[0]), max(1.0, second[3] - second[1])
        area = min(first_w * first_h, second_w * second_h) / max(first_w * first_h, second_w * second_h)
        aspect = min(first_w / first_h, second_w / second_h) / max(first_w / first_h, second_w / second_h)
        return float(0.7 * area + 0.3 * aspect)

    @staticmethod
    def _motion_similarity(previous, current, frame_w: int, frame_h: int) -> float:
        diagonal = max(1.0, (frame_w**2 + frame_h**2) ** 0.5)
        distance = ((previous[0] - current[0]) ** 2 + (previous[1] - current[1]) ** 2) ** 0.5
        return float(max(0.0, 1.0 - distance / (0.6 * diagonal)))

    @staticmethod
    def _clamp_bbox(bbox, frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = bbox
        left = max(0, min(frame_w - 1, int(round(x1))))
        top = max(0, min(frame_h - 1, int(round(y1))))
        right = max(left + 1, min(frame_w, int(round(x2))))
        bottom = max(top + 1, min(frame_h, int(round(y2))))
        return left, top, right, bottom


@dataclass(frozen=True)
class ReacquisitionDecision:
    detection: TrackedDetection | None
    score: float
    confidence_level: str
    state: IdentityLifecycleState | None


class ReacquisitionPolicy:
    """Applies the unchanged v1.0-alpha.1 gallery thresholds and confirmation window."""

    def __init__(self, min_score: float = 0.72, high_score: float = 0.84, low_score: float = 0.58, margin: float = 0.08, confirm_frames: int = 3) -> None:
        self.min_score = min_score
        self.high_score = high_score
        self.low_score = low_score
        self.margin = margin
        self.confirm_frames = confirm_frames
        self._pending_track_id: int | None = None
        self._pending_count = 0

    def set_min_score(self, min_score: float) -> None:
        self.min_score = max(0.0, min(1.0, float(min_score)))
        self.high_score = max(self.min_score, min(1.0, self.min_score + 0.12))
        self.low_score = max(0.0, min(self.min_score, self.min_score - 0.14))
        self.reset_pending()

    def reset_pending(self) -> None:
        self._pending_track_id = None
        self._pending_count = 0

    def choose(self, identity: Any, detections: list[TrackedDetection], frame, feature_gallery: Any) -> ReacquisitionDecision:
        if identity is None or identity.global_vehicle_id is None or feature_gallery is None or not detections:
            self.reset_pending()
            return ReacquisitionDecision(None, 0.0, "unknown", None)
        candidates = self.spatial_candidates(identity, detections, frame.shape)
        ranked = feature_gallery.rank_detections_for_vehicle(identity.global_vehicle_id, candidates, frame)
        if not ranked:
            return ReacquisitionDecision(None, 0.0, "none", IdentityLifecycleState.SEARCHING)
        best = ranked[0]
        second_score = ranked[1].score if len(ranked) > 1 else 0.0
        if best.score < self.low_score or best.score - second_score < self.margin:
            self.reset_pending()
            return ReacquisitionDecision(None, best.score, "low", IdentityLifecycleState.SEARCHING)
        if best.score >= self.high_score:
            self.reset_pending()
            return ReacquisitionDecision(best.detection, best.score, "high", IdentityLifecycleState.CONFIRMED)
        if best.score < self.min_score:
            self.reset_pending()
            return ReacquisitionDecision(None, best.score, "candidate", IdentityLifecycleState.CANDIDATE)
        pending_key = self.pending_key(best.detection)
        if pending_key == self._pending_track_id:
            self._pending_count += 1
        else:
            self._pending_track_id, self._pending_count = pending_key, 1
        if self._pending_count >= self.confirm_frames:
            self.reset_pending()
            return ReacquisitionDecision(best.detection, best.score, "confirmed", IdentityLifecycleState.CONFIRMED)
        return ReacquisitionDecision(None, best.score, "pending", IdentityLifecycleState.CANDIDATE)

    @staticmethod
    def pending_key(detection: TrackedDetection) -> int:
        if detection.track_id is not None:
            return int(detection.track_id)
        x1, y1, x2, y2 = detection.bbox
        return hash((int(round((x1 + x2) / 20.0)), int(round((y1 + y2) / 20.0))))

    @staticmethod
    def spatial_candidates(identity: Any, detections: list[TrackedDetection], frame_shape) -> list[TrackedDetection]:
        if not detections:
            return []
        frame_h, frame_w = frame_shape[:2]
        diagonal = max(1.0, float((frame_w**2 + frame_h**2) ** 0.5))
        predicted = (identity.last_center[0] + identity.velocity[0] * max(1, identity.lost_frames + 1), identity.last_center[1] + identity.velocity[1] * max(1, identity.lost_frames + 1))
        radius = diagonal * min(0.75, 0.25 + identity.lost_frames * 0.035)
        ranked = sorted(detections, key=lambda item: (item.center[0] - predicted[0]) ** 2 + (item.center[1] - predicted[1]) ** 2)
        nearby = [item for item in ranked if (item.center[0] - predicted[0]) ** 2 + (item.center[1] - predicted[1]) ** 2 <= radius**2]
        if nearby:
            return nearby[:6]
        return ranked[:8] if identity.lost_frames >= 5 else []


class TrackIdentityMapper:
    """Owns local-track/GID association checks and identity mutation."""

    @staticmethod
    def is_selected(identity: Any, detection: TrackedDetection) -> bool:
        if identity is None:
            return False
        if detection.track_id is not None and identity.last_track_id is not None:
            return detection.track_id == identity.last_track_id
        return identity.global_vehicle_id is not None and detection.frame_index == identity.last_frame_index and TrackIdentityMapper.bbox_iou(detection.bbox, identity.last_bbox) >= 0.80

    @staticmethod
    def bbox_iou(first, second) -> float:
        left, top, right, bottom = max(first[0], second[0]), max(first[1], second[1]), min(first[2], second[2]), min(first[3], second[3])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union > 0.0 else 0.0

    @staticmethod
    def update(identity: Any, detection: TrackedDetection) -> None:
        frame_delta = max(1, detection.frame_index - identity.last_frame_index)
        measured = ((detection.center[0] - identity.last_center[0]) / frame_delta, (detection.center[1] - identity.last_center[1]) / frame_delta)
        identity.velocity = (identity.velocity[0] * 0.65 + measured[0] * 0.35, identity.velocity[1] * 0.65 + measured[1] * 0.35)
        identity.last_track_id = detection.track_id
        identity.class_name, identity.confidence = detection.class_name, detection.confidence
        identity.last_bbox, identity.last_center = detection.bbox, detection.center
        identity.last_frame_index, identity.last_seen_timestamp = detection.frame_index, detection.timestamp
        identity.lost_frames = 0
        if detection.track_id is not None and detection.track_id not in identity.track_aliases:
            identity.track_aliases.append(detection.track_id)
            identity.track_aliases = identity.track_aliases[-12:]


class MotorSafetyPolicy:
    """Centralizes the existing motor-enable rules without changing their values."""

    @staticmethod
    def for_match(confidence_level: str) -> bool:
        return confidence_level in {"high", "confirmed", "track"}

    @staticmethod
    def for_coasting(lost_frames: int) -> bool:
        return lost_frames <= 3

    @staticmethod
    def can_predict(identity: Any, frame_shape) -> bool:
        frame_h, frame_w = frame_shape[:2]
        margin_x, margin_y = frame_w * 0.08, frame_h * 0.08
        x, y = identity.last_center
        if x <= margin_x or x >= frame_w - margin_x or y <= margin_y or y >= frame_h - margin_y:
            return False
        speed = (identity.velocity[0] ** 2 + identity.velocity[1] ** 2) ** 0.5
        max_speed = max(frame_w, frame_h) * (0.08 if identity.lost_frames <= 3 else 0.12)
        return speed <= max_speed
