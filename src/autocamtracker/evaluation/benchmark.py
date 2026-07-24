"""Comparable benchmark results and the versioned V2.2 score policy."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable

from autocamtracker.evaluation.offline_replay import OfflineReplayReport


BENCHMARK_SCHEMA_VERSION = 1
MAX_COMPARE_MODELS = 5
MAX_SCORE = 1_000_000


def _clamp(value: float | None, low: float = 0.0, high: float = 1.0) -> float | None:
    if value is None:
        return None
    return max(low, min(high, float(value)))


def _inverse_ratio(value: float | None, budget: float) -> float | None:
    if value is None:
        return None
    return _clamp(1.0 - float(value) / max(1e-9, budget))


@dataclass(frozen=True)
class BenchmarkAxes:
    detection: float | None = None
    tracking: float | None = None
    identity: float | None = None
    framing: float | None = None
    control: float | None = None
    realtime: float | None = None

    def available(self) -> dict[str, float]:
        return {
            name: value
            for name, value in (
                ("Detection", self.detection),
                ("Tracking", self.tracking),
                ("Identity", self.identity),
                ("Framing", self.framing),
                ("Control", self.control),
                ("Realtime", self.realtime),
            )
            if value is not None
        }

    @property
    def coverage(self) -> float:
        return len(self.available()) / 6.0


@dataclass(frozen=True)
class BenchmarkScore:
    total: int
    coverage: float
    axes: BenchmarkAxes
    profile: str
    safety_passed: bool


@dataclass(frozen=True)
class ModelBenchmarkResult:
    model_name: str
    model_path: str
    tracker: str
    dataset_version: str
    metrics: dict[str, float | int | None]
    score: BenchmarkScore
    reid_model_path: str | None = None
    run_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "model_name": self.model_name,
            "model_path": self.model_path,
            "reid_model_path": self.reid_model_path,
            "tracker": self.tracker,
            "dataset_version": self.dataset_version,
            "run_id": self.run_id,
            "metadata": self.metadata,
            "metrics": self.metrics,
            "score": {
                "total": self.score.total,
                "coverage": self.score.coverage,
                "profile": self.score.profile,
                "safety_passed": self.score.safety_passed,
                "axes": {
                    "detection": self.score.axes.detection,
                    "tracking": self.score.axes.tracking,
                    "identity": self.score.axes.identity,
                    "framing": self.score.axes.framing,
                    "control": self.score.axes.control,
                    "realtime": self.score.axes.realtime,
                },
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelBenchmarkResult":
        if int(payload.get("schema_version", 0)) != BENCHMARK_SCHEMA_VERSION:
            raise ValueError("Unsupported benchmark result schema")
        score_payload = payload["score"]
        axes_payload = score_payload["axes"]
        axes = BenchmarkAxes(
            detection=_optional_float(axes_payload.get("detection")),
            tracking=_optional_float(axes_payload.get("tracking")),
            identity=_optional_float(axes_payload.get("identity")),
            framing=_optional_float(axes_payload.get("framing")),
            control=_optional_float(axes_payload.get("control")),
            realtime=_optional_float(axes_payload.get("realtime")),
        )
        score = BenchmarkScore(
            total=int(score_payload["total"]),
            coverage=float(score_payload["coverage"]),
            axes=axes,
            profile=str(score_payload["profile"]),
            safety_passed=bool(score_payload["safety_passed"]),
        )
        return cls(
            model_name=str(payload["model_name"]),
            model_path=str(payload["model_path"]),
            reid_model_path=payload.get("reid_model_path"),
            tracker=str(payload["tracker"]),
            dataset_version=str(payload["dataset_version"]),
            run_id=str(payload.get("run_id", "")),
            metadata=dict(payload.get("metadata", {})),
            metrics=dict(payload["metrics"]),
            score=score,
        )


def score_offline_report(
    report: OfflineReplayReport,
    *,
    profile: str = "Full Pipeline",
    safety_passed: bool = True,
) -> BenchmarkScore:
    """Return an AnTuTu-style score without hiding unavailable evaluation axes."""

    detection_values = [
        _clamp(report.detection.map50_95),
        _clamp(report.detection.precision),
        _clamp(report.detection.recall),
    ]
    detection = _weighted_available(detection_values, (0.60, 0.20, 0.20))

    tracking_values = [
        _clamp(report.tracking.hota),
        _clamp(report.tracking.idf1),
        _clamp(report.tracking.mota),
    ]
    tracking = _weighted_available(tracking_values, (0.40, 0.40, 0.20))

    identity_values = [
        _clamp(report.reid.rank1),
        _clamp(report.reid.reacquire_success_rate),
        (
            1.0 - _clamp(report.reid.false_reacquire_rate)
            if report.reid.false_reacquire_rate is not None
            else None
        ),
    ]
    identity = _weighted_available(identity_values, (0.35, 0.40, 0.25))

    framing = (
        1.0 - _clamp(report.control.target_out_of_frame_ratio)
        if report.control.target_out_of_frame_ratio is not None
        else None
    )
    control_values = [
        _inverse_ratio(report.control.jitter, 0.25),
        _inverse_ratio(report.control.overshoot, 0.50),
        _inverse_ratio(report.control.settling_time_ms, 2_000.0),
    ]
    control = _weighted_available(control_values, (0.40, 0.35, 0.25))

    realtime_values = [
        _clamp(report.system.fps / 30.0) if report.system.fps is not None else None,
        _inverse_ratio(report.system.latency_p95_ms, 150.0),
        (
            1.0 - _clamp(report.system.dropped_frame_rate)
            if report.system.dropped_frame_rate is not None
            else None
        ),
    ]
    realtime = _weighted_available(realtime_values, (0.40, 0.40, 0.20))

    axes = BenchmarkAxes(detection, tracking, identity, framing, control, realtime)
    available = axes.available()
    total = round(
        MAX_SCORE * sum(available.values()) / len(available)
    ) if available and safety_passed else 0
    return BenchmarkScore(
        total=total,
        coverage=axes.coverage,
        axes=axes,
        profile=profile,
        safety_passed=safety_passed,
    )


def result_from_report(
    report: OfflineReplayReport,
    *,
    model_path: Path | str,
    tracker: str,
    dataset_version: str,
    reid_model_path: Path | str | None = None,
    profile: str = "Full Pipeline",
    safety_passed: bool = True,
    run_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> ModelBenchmarkResult:
    model = Path(model_path)
    metrics = {
        "mAP50": report.detection.map50,
        "mAP50-95": report.detection.map50_95,
        "Precision": report.detection.precision,
        "Recall": report.detection.recall,
        "HOTA": report.tracking.hota,
        "IDF1": report.tracking.idf1,
        "MOTA": report.tracking.mota,
        "ID switches": report.tracking.id_switches,
        "Fragmentation": report.tracking.fragmentation,
        "Rank-1": report.reid.rank1,
        "Rank-5": report.reid.rank5,
        "MRR": report.reid.mean_reciprocal_rank,
        "False reacquire rate": report.reid.false_reacquire_rate,
        "Reacquire success rate": report.reid.reacquire_success_rate,
        "FPS": report.system.fps,
        "Latency p50 ms": report.system.latency_p50_ms,
        "Latency p95 ms": report.system.latency_p95_ms,
        "Latency p99 ms": report.system.latency_p99_ms,
        "Dropped frame rate": report.system.dropped_frame_rate,
        "Overshoot": report.control.overshoot,
        "Settling time ms": report.control.settling_time_ms,
        "Jitter": report.control.jitter,
        "Target out-of-frame ratio": report.control.target_out_of_frame_ratio,
    }
    return ModelBenchmarkResult(
        model_name=model.stem,
        model_path=str(model),
        reid_model_path=str(reid_model_path) if reid_model_path else None,
        tracker=tracker,
        dataset_version=dataset_version,
        run_id=run_id,
        metadata=dict(metadata or {}),
        metrics=metrics,
        score=score_offline_report(
            report, profile=profile, safety_passed=safety_passed
        ),
    )


def save_results(path: Path | str, results: Iterable[ModelBenchmarkResult]) -> None:
    payload = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "results": [item.to_dict() for item in results],
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_results(path: Path | str) -> list[ModelBenchmarkResult]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != BENCHMARK_SCHEMA_VERSION:
        raise ValueError("Unsupported benchmark collection schema")
    results = [ModelBenchmarkResult.from_dict(item) for item in payload.get("results", [])]
    if len(results) > MAX_COMPARE_MODELS:
        raise ValueError(f"A comparison supports at most {MAX_COMPARE_MODELS} models")
    return results


def _weighted_available(
    values: list[float | None], weights: tuple[float, ...]
) -> float | None:
    available = [(value, weight) for value, weight in zip(values, weights) if value is not None]
    if not available:
        return None
    weight_total = sum(weight for _, weight in available)
    return sum(float(value) * weight for value, weight in available) / weight_total


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
