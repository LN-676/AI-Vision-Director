"""Offline throughput and capture-to-command latency metrics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemSample:
    capture_timestamp_ms: float
    command_timestamp_ms: float | None
    dropped: bool = False


@dataclass(frozen=True)
class SystemMetrics:
    fps: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_p99_ms: float | None
    dropped_frame_rate: float | None


def evaluate_system(samples: list[SystemSample]) -> SystemMetrics:
    processed = [sample for sample in samples if not sample.dropped]
    captures = [sample.capture_timestamp_ms for sample in samples]
    if len(captures) >= 2 and max(captures) > min(captures):
        source_fps = (len(captures) - 1) * 1000.0 / (max(captures) - min(captures))
        fps = source_fps * len(processed) / len(samples)
    else:
        fps = None
    latencies = sorted(
        max(0.0, sample.command_timestamp_ms - sample.capture_timestamp_ms)
        for sample in processed
        if sample.command_timestamp_ms is not None
    )
    dropped_rate = sum(sample.dropped for sample in samples) / len(samples) if samples else None
    return SystemMetrics(
        fps=fps,
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_p99_ms=_percentile(latencies, 0.99),
        dropped_frame_rate=dropped_rate,
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * percentile
    lower = int(position)
    upper = min(len(values) - 1, lower + 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction
