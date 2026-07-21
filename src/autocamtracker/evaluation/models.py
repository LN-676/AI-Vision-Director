"""Implementation-neutral records consumed by offline evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class EvaluationObject:
    bbox: tuple[float, float, float, float]
    class_id: int
    confidence: float = 1.0
    identity_id: int | None = None
    track_id: int | None = None

    def __post_init__(self) -> None:
        if len(self.bbox) != 4:
            raise ValueError("bbox must contain four coordinates")
        if self.bbox[2] < self.bbox[0] or self.bbox[3] < self.bbox[1]:
            raise ValueError("bbox edges are inverted")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True)
class ReIDObservation:
    expected_identity_id: int
    ranked_identity_ids: tuple[int, ...] = ()
    reacquire_attempted: bool = False
    reacquired_identity_id: int | None = None


@dataclass(frozen=True)
class ControlObservation:
    timestamp_ms: float
    error_x: float
    error_y: float
    command_x: float = 0.0
    command_y: float = 0.0
    target_in_frame: bool = True


@dataclass(frozen=True)
class ReplayOutput:
    detections: tuple[EvaluationObject, ...] = ()
    command_timestamp_ms: float | None = None
    reid: ReIDObservation | None = None
    control: ControlObservation | None = None


@dataclass(frozen=True)
class ReplayFrame:
    frame_index: int
    capture_timestamp_ms: float
    ground_truth: tuple[EvaluationObject, ...] = ()
    payload: Any = field(default=None, repr=False, compare=False)
    dropped: bool = False
    recorded_output: ReplayOutput | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class FrameEvaluation:
    frame_index: int
    ground_truth: tuple[EvaluationObject, ...]
    predictions: tuple[EvaluationObject, ...]


def intersection_over_union(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0.0 else 0.0


def match_frame(
    ground_truth: tuple[EvaluationObject, ...],
    predictions: tuple[EvaluationObject, ...],
    iou_threshold: float,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    candidates = []
    for truth_index, truth in enumerate(ground_truth):
        for prediction_index, prediction in enumerate(predictions):
            if truth.class_id != prediction.class_id:
                continue
            iou = intersection_over_union(truth.bbox, prediction.bbox)
            if iou >= iou_threshold:
                candidates.append((iou, truth_index, prediction_index))
    matches = []
    used_truth = set()
    used_predictions = set()
    for _, truth_index, prediction_index in sorted(candidates, reverse=True):
        if truth_index in used_truth or prediction_index in used_predictions:
            continue
        used_truth.add(truth_index)
        used_predictions.add(prediction_index)
        matches.append((truth_index, prediction_index))
    unmatched_truth = [index for index in range(len(ground_truth)) if index not in used_truth]
    unmatched_predictions = [index for index in range(len(predictions)) if index not in used_predictions]
    return matches, unmatched_truth, unmatched_predictions
