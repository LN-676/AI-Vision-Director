"""Offline multi-object tracking metrics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from math import sqrt
from statistics import fmean

from autocamtracker.evaluation.models import FrameEvaluation, match_frame


@dataclass(frozen=True)
class TrackingMetrics:
    hota: float | None
    idf1: float | None
    mota: float | None
    id_switches: int
    fragmentation: int


def evaluate_tracking(frames: list[FrameEvaluation]) -> TrackingMetrics:
    thresholds = [round(index * 0.05, 2) for index in range(1, 20)]
    hota_values = [_hota_at_threshold(frames, threshold) for threshold in thresholds]
    false_positives = false_negatives = 0
    pair_counts: Counter[tuple[int, int]] = Counter()
    truth_detections = prediction_detections = 0
    id_switches = 0
    fragmentation = 0
    last_track_for_truth: dict[int, int] = {}
    active_truth: dict[int, bool] = {}
    seen_segment: set[int] = set()

    for frame in sorted(frames, key=lambda item: item.frame_index):
        matches, unmatched_truth, unmatched_predictions = match_frame(
            frame.ground_truth, frame.predictions, 0.5
        )
        false_negatives += len(unmatched_truth)
        false_positives += len(unmatched_predictions)
        truth_detections += sum(item.identity_id is not None for item in frame.ground_truth)
        prediction_detections += sum(item.track_id is not None for item in frame.predictions)
        matched_truth_ids = set()
        for truth_index, prediction_index in matches:
            truth = frame.ground_truth[truth_index]
            prediction = frame.predictions[prediction_index]
            if truth.identity_id is None or prediction.track_id is None:
                continue
            truth_id = truth.identity_id
            track_id = prediction.track_id
            pair_counts[(truth_id, track_id)] += 1
            matched_truth_ids.add(truth_id)
            if truth_id in last_track_for_truth and last_track_for_truth[truth_id] != track_id:
                id_switches += 1
            last_track_for_truth[truth_id] = track_id
            if not active_truth.get(truth_id, False) and truth_id in seen_segment:
                fragmentation += 1
            active_truth[truth_id] = True
            seen_segment.add(truth_id)
        for truth in frame.ground_truth:
            if truth.identity_id is not None and truth.identity_id not in matched_truth_ids:
                active_truth[truth.identity_id] = False

    total_truth = sum(len(frame.ground_truth) for frame in frames)
    mota = (
        1.0 - (false_negatives + false_positives + id_switches) / total_truth
        if total_truth else None
    )
    identity_true_positives = _maximum_assignment(pair_counts)
    idf1_denominator = truth_detections + prediction_detections
    idf1 = 2.0 * identity_true_positives / idf1_denominator if idf1_denominator else None
    available_hota = [value for value in hota_values if value is not None]
    return TrackingMetrics(
        hota=fmean(available_hota) if available_hota else None,
        idf1=idf1,
        mota=mota,
        id_switches=id_switches,
        fragmentation=fragmentation,
    )


def _hota_at_threshold(frames: list[FrameEvaluation], threshold: float) -> float | None:
    true_positives = false_positives = false_negatives = 0
    pairs: Counter[tuple[int, int]] = Counter()
    truth_totals: Counter[int] = Counter()
    prediction_totals: Counter[int] = Counter()
    for frame in frames:
        for truth in frame.ground_truth:
            if truth.identity_id is not None:
                truth_totals[truth.identity_id] += 1
        for prediction in frame.predictions:
            if prediction.track_id is not None:
                prediction_totals[prediction.track_id] += 1
        matches, unmatched_truth, unmatched_predictions = match_frame(
            frame.ground_truth, frame.predictions, threshold
        )
        true_positives += len(matches)
        false_negatives += len(unmatched_truth)
        false_positives += len(unmatched_predictions)
        for truth_index, prediction_index in matches:
            truth_id = frame.ground_truth[truth_index].identity_id
            track_id = frame.predictions[prediction_index].track_id
            if truth_id is not None and track_id is not None:
                pairs[(truth_id, track_id)] += 1
    denominator = true_positives + false_positives + false_negatives
    if denominator == 0:
        return None
    detection_accuracy = true_positives / denominator
    association_sum = 0.0
    associated_matches = 0
    for (truth_id, track_id), count in pairs.items():
        association_iou = count / max(1, truth_totals[truth_id] + prediction_totals[track_id] - count)
        association_sum += count * association_iou
        associated_matches += count
    association_accuracy = association_sum / associated_matches if associated_matches else 0.0
    return sqrt(detection_accuracy * association_accuracy)


def _maximum_assignment(pair_counts: Counter[tuple[int, int]]) -> int:
    if not pair_counts:
        return 0
    truth_ids = sorted({pair[0] for pair in pair_counts})
    track_ids = sorted({pair[1] for pair in pair_counts})
    if len(track_ids) > 15:
        used_truth = set()
        used_tracks = set()
        total = 0
        for (truth_id, track_id), count in pair_counts.most_common():
            if truth_id not in used_truth and track_id not in used_tracks:
                used_truth.add(truth_id)
                used_tracks.add(track_id)
                total += count
        return total

    @lru_cache(maxsize=None)
    def solve(truth_index: int, used_tracks: int) -> int:
        if truth_index >= len(truth_ids):
            return 0
        best = solve(truth_index + 1, used_tracks)
        truth_id = truth_ids[truth_index]
        for track_index, track_id in enumerate(track_ids):
            if used_tracks & (1 << track_index):
                continue
            best = max(
                best,
                pair_counts[(truth_id, track_id)]
                + solve(truth_index + 1, used_tracks | (1 << track_index)),
            )
        return best

    return solve(0, 0)
