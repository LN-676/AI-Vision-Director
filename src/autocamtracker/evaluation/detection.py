"""Offline object-detection metrics."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from autocamtracker.evaluation.models import FrameEvaluation, intersection_over_union, match_frame


@dataclass(frozen=True)
class DetectionMetrics:
    map50: float | None
    map50_95: float | None
    precision: float | None
    recall: float | None


def evaluate_detection(frames: list[FrameEvaluation]) -> DetectionMetrics:
    thresholds = [round(0.50 + index * 0.05, 2) for index in range(10)]
    classes = sorted({item.class_id for frame in frames for item in frame.ground_truth})
    per_threshold = {
        threshold: [_average_precision(frames, class_id, threshold) for class_id in classes]
        for threshold in thresholds
    }
    map_by_threshold = {
        threshold: fmean(value for value in values if value is not None)
        if any(value is not None for value in values) else None
        for threshold, values in per_threshold.items()
    }
    true_positive = false_positive = false_negative = 0
    for frame in frames:
        matches, unmatched_truth, unmatched_predictions = match_frame(
            frame.ground_truth, frame.predictions, 0.5
        )
        true_positive += len(matches)
        false_negative += len(unmatched_truth)
        false_positive += len(unmatched_predictions)
    precision = _divide(true_positive, true_positive + false_positive)
    recall = _divide(true_positive, true_positive + false_negative)
    available_maps = [value for value in map_by_threshold.values() if value is not None]
    return DetectionMetrics(
        map50=map_by_threshold[0.5],
        map50_95=fmean(available_maps) if available_maps else None,
        precision=precision,
        recall=recall,
    )


def _average_precision(frames: list[FrameEvaluation], class_id: int, threshold: float) -> float | None:
    truth_by_frame = {
        frame.frame_index: [item for item in frame.ground_truth if item.class_id == class_id]
        for frame in frames
    }
    truth_count = sum(len(items) for items in truth_by_frame.values())
    if truth_count == 0:
        return None
    predictions = sorted(
        (
            (item.confidence, frame.frame_index, item)
            for frame in frames
            for item in frame.predictions
            if item.class_id == class_id
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    matched: dict[int, set[int]] = {}
    true_positives = []
    false_positives = []
    for _, frame_index, prediction in predictions:
        best_index = None
        best_iou = threshold
        used = matched.setdefault(frame_index, set())
        for truth_index, truth in enumerate(truth_by_frame.get(frame_index, [])):
            if truth_index in used:
                continue
            iou = intersection_over_union(truth.bbox, prediction.bbox)
            if iou >= best_iou:
                best_iou = iou
                best_index = truth_index
        if best_index is None:
            true_positives.append(0)
            false_positives.append(1)
        else:
            used.add(best_index)
            true_positives.append(1)
            false_positives.append(0)
    if not predictions:
        return 0.0
    cumulative_tp = 0
    cumulative_fp = 0
    precisions = []
    recalls = []
    for tp, fp in zip(true_positives, false_positives):
        cumulative_tp += tp
        cumulative_fp += fp
        precisions.append(cumulative_tp / max(1, cumulative_tp + cumulative_fp))
        recalls.append(cumulative_tp / truth_count)
    interpolated = []
    for recall_threshold in (index / 100.0 for index in range(101)):
        candidates = [precision for precision, recall in zip(precisions, recalls) if recall >= recall_threshold]
        interpolated.append(max(candidates, default=0.0))
    return fmean(interpolated)


def _divide(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
