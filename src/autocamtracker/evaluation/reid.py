"""Offline retrieval and reacquisition metrics for ReID."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from autocamtracker.evaluation.models import ReIDObservation


@dataclass(frozen=True)
class ReIDMetrics:
    rank1: float | None
    rank5: float | None
    mean_average_precision: float | None
    false_reacquire_rate: float | None
    reacquire_success_rate: float | None


def evaluate_reid(observations: list[ReIDObservation]) -> ReIDMetrics:
    if observations:
        rank1 = fmean(
            bool(item.ranked_identity_ids and item.ranked_identity_ids[0] == item.expected_identity_id)
            for item in observations
        )
        rank5 = fmean(
            item.expected_identity_id in item.ranked_identity_ids[:5]
            for item in observations
        )
        average_precision = fmean(_reciprocal_rank(item) for item in observations)
    else:
        rank1 = rank5 = average_precision = None
    attempts = [item for item in observations if item.reacquire_attempted]
    if attempts:
        successes = sum(item.reacquired_identity_id == item.expected_identity_id for item in attempts)
        false_reacquires = sum(
            item.reacquired_identity_id is not None
            and item.reacquired_identity_id != item.expected_identity_id
            for item in attempts
        )
        success_rate = successes / len(attempts)
        false_rate = false_reacquires / len(attempts)
    else:
        success_rate = false_rate = None
    return ReIDMetrics(rank1, rank5, average_precision, false_rate, success_rate)


def _reciprocal_rank(observation: ReIDObservation) -> float:
    for rank, identity_id in enumerate(observation.ranked_identity_ids, start=1):
        if identity_id == observation.expected_identity_id:
            return 1.0 / rank
    return 0.0
