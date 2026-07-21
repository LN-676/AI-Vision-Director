"""Versioned, deterministic GID-loss benchmark built on Phase 9 replay data."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from autocamtracker.evaluation.models import GIDObservation, ReplayFrame
from autocamtracker.evaluation.offline_replay import load_replay_jsonl


DEFAULT_MANIFEST = Path("evaluation") / "gid_loss_scenarios.json"
REQUIRED_SCENARIOS = (
    "occlusion",
    "vehicle_crossing",
    "fast_lateral_motion",
    "re_entry",
    "same_color",
    "same_vehicle_model",
    "similar_livery",
    "fast_camera_pan",
    "zoom_change",
    "motion_blur",
    "backlight",
    "low_light",
    "far_distance",
    "scene_cut",
)


@dataclass(frozen=True)
class GIDLossThresholds:
    gid_lock_rate_min: float
    max_consecutive_lost_frames: int
    id_switches_max: int
    median_reacquire_frames_max: float
    motor_unsafe_frames_max: int

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "GIDLossThresholds":
        thresholds = cls(
            gid_lock_rate_min=float(payload["gid_lock_rate_min"]),
            max_consecutive_lost_frames=int(payload["max_consecutive_lost_frames"]),
            id_switches_max=int(payload["id_switches_max"]),
            median_reacquire_frames_max=float(payload["median_reacquire_frames_max"]),
            motor_unsafe_frames_max=int(payload["motor_unsafe_frames_max"]),
        )
        if not 0.0 <= thresholds.gid_lock_rate_min <= 1.0:
            raise ValueError("gid_lock_rate_min must be between 0.0 and 1.0")
        if min(
            thresholds.max_consecutive_lost_frames,
            thresholds.id_switches_max,
            thresholds.median_reacquire_frames_max,
            thresholds.motor_unsafe_frames_max,
        ) < 0:
            raise ValueError("GID loss thresholds cannot be negative")
        return thresholds

    def to_dict(self) -> dict[str, float | int]:
        return {
            "gid_lock_rate_min": self.gid_lock_rate_min,
            "max_consecutive_lost_frames": self.max_consecutive_lost_frames,
            "id_switches_max": self.id_switches_max,
            "median_reacquire_frames_max": self.median_reacquire_frames_max,
            "motor_unsafe_frames_max": self.motor_unsafe_frames_max,
        }


@dataclass(frozen=True)
class GIDLossScenarioSpec:
    scenario_id: str
    name: str
    replay_path: Path
    description: str
    minimum_frames: int

    @property
    def video_path(self) -> Path:
        """Deprecated Phase 5 name retained for source compatibility."""
        return self.replay_path


@dataclass(frozen=True)
class GIDLossSpec:
    version: int
    dataset_version: str
    replay_root: Path
    thresholds: GIDLossThresholds
    scenarios: tuple[GIDLossScenarioSpec, ...]

    @property
    def metrics(self) -> dict[str, float | int]:
        """Deprecated Phase 5 name retained for source compatibility."""
        return self.thresholds.to_dict()

    @property
    def missing_replays(self) -> tuple[Path, ...]:
        return tuple(item.replay_path for item in self.scenarios if not item.replay_path.is_file())

    def summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "dataset_version": self.dataset_version,
            "scenario_count": len(self.scenarios),
            "missing_replay_count": len(self.missing_replays),
            "missing_video_count": len(self.missing_replays),
            "thresholds": self.thresholds.to_dict(),
            "metrics": self.thresholds.to_dict(),
            "scenarios": [
                {
                    "id": item.scenario_id,
                    "name": item.name,
                    "replay": str(item.replay_path),
                    "video": str(item.replay_path),
                    "exists": item.replay_path.is_file(),
                }
                for item in self.scenarios
            ],
        }


@dataclass(frozen=True)
class GIDLossMetrics:
    frame_count: int
    visible_frame_count: int
    locked_frame_count: int
    gid_lock_rate: float
    max_consecutive_lost_frames: int
    id_switches: int
    reacquire_events: int
    median_reacquire_frames: float
    motor_unsafe_frames: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "frame_count": self.frame_count,
            "visible_frame_count": self.visible_frame_count,
            "locked_frame_count": self.locked_frame_count,
            "gid_lock_rate": self.gid_lock_rate,
            "max_consecutive_lost_frames": self.max_consecutive_lost_frames,
            "id_switches": self.id_switches,
            "reacquire_events": self.reacquire_events,
            "median_reacquire_frames": self.median_reacquire_frames,
            "motor_unsafe_frames": self.motor_unsafe_frames,
        }


@dataclass(frozen=True)
class GIDLossScenarioReport:
    scenario_id: str
    name: str
    metrics: GIDLossMetrics
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.scenario_id,
            "name": self.name,
            "passed": self.passed,
            "failures": list(self.failures),
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True)
class GIDLossBenchmarkReport:
    benchmark_version: int
    dataset_version: str
    thresholds: GIDLossThresholds
    scenarios: tuple[GIDLossScenarioReport, ...]

    @property
    def passed(self) -> bool:
        return bool(self.scenarios) and all(item.passed for item in self.scenarios)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_version": self.benchmark_version,
            "dataset_version": self.dataset_version,
            "passed": self.passed,
            "thresholds": self.thresholds.to_dict(),
            "scenarios": [item.to_dict() for item in self.scenarios],
        }


class GIDLossBenchmarkRunner:
    def __init__(self, spec: GIDLossSpec) -> None:
        self.spec = spec

    def run(self) -> GIDLossBenchmarkReport:
        missing = self.spec.missing_replays
        if missing:
            formatted = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(f"Missing GID loss replay files: {formatted}")
        reports = tuple(self._run_scenario(item) for item in self.spec.scenarios)
        return GIDLossBenchmarkReport(
            benchmark_version=self.spec.version,
            dataset_version=self.spec.dataset_version,
            thresholds=self.spec.thresholds,
            scenarios=reports,
        )

    def _run_scenario(self, scenario: GIDLossScenarioSpec) -> GIDLossScenarioReport:
        frames = load_replay_jsonl(scenario.replay_path)
        if len(frames) < scenario.minimum_frames:
            raise ValueError(
                f"Scenario {scenario.scenario_id!r} requires at least "
                f"{scenario.minimum_frames} frames; found {len(frames)}"
            )
        observations = _observations(frames, scenario.scenario_id)
        metrics = evaluate_gid_loss(observations)
        return GIDLossScenarioReport(
            scenario_id=scenario.scenario_id,
            name=scenario.name,
            metrics=metrics,
            failures=_threshold_failures(metrics, self.spec.thresholds),
        )


def evaluate_gid_loss(observations: Iterable[GIDObservation]) -> GIDLossMetrics:
    ordered = tuple(observations)
    if not ordered:
        raise ValueError("GID loss evaluation requires at least one observation")
    expected_ids = {item.expected_identity_id for item in ordered}
    if len(expected_ids) != 1:
        raise ValueError("A GID loss scenario must evaluate exactly one expected identity")

    visible = locked = unsafe = switches = 0
    lost_streak = max_lost_streak = 0
    previous_visible = False
    had_lock = False
    pending_reacquire = False
    reacquire_frames = 0
    reacquire_samples: list[int] = []
    previous_assignment: int | None = None

    for item in ordered:
        if not item.motor_safe:
            unsafe += 1
        if not item.target_visible:
            if previous_visible and had_lock:
                pending_reacquire = True
                reacquire_frames = 0
            previous_visible = False
            lost_streak = 0
            previous_assignment = None
            continue

        visible += 1
        is_locked = item.assigned_identity_id == item.expected_identity_id
        if is_locked:
            locked += 1
            had_lock = True
            if pending_reacquire:
                reacquire_samples.append(reacquire_frames)
                pending_reacquire = False
            lost_streak = 0
        else:
            lost_streak += 1
            max_lost_streak = max(max_lost_streak, lost_streak)
            if had_lock and not pending_reacquire:
                pending_reacquire = True
                reacquire_frames = 0
            if pending_reacquire:
                reacquire_frames += 1

        assignment = item.assigned_identity_id
        if assignment is not None and assignment != item.expected_identity_id:
            if assignment != previous_assignment:
                switches += 1
        previous_assignment = assignment
        previous_visible = True

    return GIDLossMetrics(
        frame_count=len(ordered),
        visible_frame_count=visible,
        locked_frame_count=locked,
        gid_lock_rate=locked / visible if visible else 0.0,
        max_consecutive_lost_frames=max_lost_streak,
        id_switches=switches,
        reacquire_events=len(reacquire_samples),
        median_reacquire_frames=float(median(reacquire_samples)) if reacquire_samples else 0.0,
        motor_unsafe_frames=unsafe,
    )


def load_gid_loss_spec(manifest_path: Path | str = DEFAULT_MANIFEST) -> GIDLossSpec:
    manifest = Path(manifest_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    replay_root = _resolve_path(manifest.parent, Path(payload["replay_root"]))
    raw_scenarios = payload.get("scenarios", [])
    ids = tuple(str(item["id"]) for item in raw_scenarios)
    if len(ids) != len(set(ids)):
        raise ValueError("GID loss scenario ids must be unique")
    missing = [item for item in REQUIRED_SCENARIOS if item not in ids]
    unexpected = [item for item in ids if item not in REQUIRED_SCENARIOS]
    if missing or unexpected:
        raise ValueError(f"Invalid GID loss scenario set; missing={missing}, unexpected={unexpected}")
    scenarios = tuple(
        GIDLossScenarioSpec(
            scenario_id=str(item["id"]),
            name=str(item["name"]),
            replay_path=replay_root / str(item["replay"]),
            description=str(item.get("description", "")),
            minimum_frames=int(item.get("minimum_frames", 1)),
        )
        for item in raw_scenarios
    )
    if any(item.minimum_frames < 1 for item in scenarios):
        raise ValueError("minimum_frames must be at least 1")
    return GIDLossSpec(
        version=int(payload["version"]),
        dataset_version=str(payload["dataset_version"]),
        replay_root=replay_root,
        thresholds=GIDLossThresholds.from_mapping(payload["thresholds"]),
        scenarios=scenarios,
    )


def _observations(frames: list[ReplayFrame], scenario_id: str) -> tuple[GIDObservation, ...]:
    observations = []
    for frame in frames:
        if frame.recorded_output is None or frame.recorded_output.gid is None:
            raise ValueError(
                f"Scenario {scenario_id!r} frame {frame.frame_index} has no output.gid annotation"
            )
        observations.append(frame.recorded_output.gid)
    return tuple(observations)


def _threshold_failures(
    metrics: GIDLossMetrics, thresholds: GIDLossThresholds
) -> tuple[str, ...]:
    failures = []
    comparisons = (
        (metrics.gid_lock_rate < thresholds.gid_lock_rate_min, "gid_lock_rate"),
        (
            metrics.max_consecutive_lost_frames > thresholds.max_consecutive_lost_frames,
            "max_consecutive_lost_frames",
        ),
        (metrics.id_switches > thresholds.id_switches_max, "id_switches"),
        (
            metrics.median_reacquire_frames > thresholds.median_reacquire_frames_max,
            "median_reacquire_frames",
        ),
        (metrics.motor_unsafe_frames > thresholds.motor_unsafe_frames_max, "motor_unsafe_frames"),
    )
    failures.extend(name for failed, name in comparisons if failed)
    return tuple(failures)


def _resolve_path(manifest_dir: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    project_root = manifest_dir.parent if manifest_dir.name == "evaluation" else manifest_dir
    return project_root / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Phase 10 GID loss benchmark")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = GIDLossBenchmarkRunner(load_gid_loss_spec(args.manifest)).run()
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
