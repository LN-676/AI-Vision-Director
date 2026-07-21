"""Offline closed-loop camera-control quality metrics."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, sqrt

from autocamtracker.evaluation.models import ControlObservation


@dataclass(frozen=True)
class ControlMetrics:
    overshoot: float | None
    settling_time_ms: float | None
    jitter: float | None
    target_out_of_frame_ratio: float | None


def evaluate_control(
    observations: list[ControlObservation],
    *,
    settling_tolerance: float = 0.05,
) -> ControlMetrics:
    ordered = sorted(observations, key=lambda item: item.timestamp_ms)
    if not ordered:
        return ControlMetrics(None, None, None, None)
    overshoot = _overshoot(ordered)
    settling_time = _settling_time(ordered, settling_tolerance)
    if len(ordered) >= 2:
        changes = [
            hypot(current.command_x - previous.command_x, current.command_y - previous.command_y)
            for previous, current in zip(ordered, ordered[1:])
        ]
        jitter = sqrt(sum(value * value for value in changes) / len(changes))
    else:
        jitter = 0.0
    out_ratio = sum(not item.target_in_frame for item in ordered) / len(ordered)
    return ControlMetrics(overshoot, settling_time, jitter, out_ratio)


def _overshoot(observations: list[ControlObservation]) -> float | None:
    if not observations:
        return None
    ratios = []
    for attribute in ("error_x", "error_y"):
        values = [float(getattr(item, attribute)) for item in observations]
        initial = values[0]
        if abs(initial) <= 1e-12:
            ratios.append(0.0)
            continue
        opposite = [abs(value) for value in values if value * initial < 0.0]
        ratios.append(max(opposite, default=0.0) / abs(initial))
    return max(ratios)


def _settling_time(
    observations: list[ControlObservation],
    tolerance: float,
) -> float | None:
    if not observations:
        return None
    for index, observation in enumerate(observations):
        if all(
            item.target_in_frame and hypot(item.error_x, item.error_y) <= tolerance
            for item in observations[index:]
        ):
            return max(0.0, observation.timestamp_ms - observations[0].timestamp_ms)
    return None
