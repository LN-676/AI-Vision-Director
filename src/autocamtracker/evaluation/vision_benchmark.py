"""Sequential video/model benchmark execution for reproducible comparisons."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Callable, Iterable

from autocamtracker.evaluation.benchmark import (
    MAX_COMPARE_MODELS,
    ModelBenchmarkResult,
    result_from_report,
    save_results,
)
from autocamtracker.evaluation.models import EvaluationObject, ReplayFrame, ReplayOutput
from autocamtracker.evaluation.offline_replay import OfflineReplayRunner, load_replay_jsonl
from autocamtracker.vision.detector import VideoDetector
from autocamtracker.vision.types import InputConfig


ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class VisionBenchmarkRequest:
    video_path: Path
    annotation_path: Path
    model_paths: tuple[Path, ...]
    tracker: str = "botsort"
    dataset_version: str = "local-golden-v1"
    confidence_threshold: float = 0.25
    detector_imgsz: int | None = 640
    warmup_frames: int = 3

    def validate(self) -> None:
        if not self.video_path.is_file():
            raise FileNotFoundError(f"Benchmark video not found: {self.video_path}")
        if not self.annotation_path.is_file():
            raise FileNotFoundError(
                f"Benchmark annotation not found: {self.annotation_path}"
            )
        if not 1 <= len(self.model_paths) <= MAX_COMPARE_MODELS:
            raise ValueError(
                f"Select between 1 and {MAX_COMPARE_MODELS} detection models"
            )
        missing = [path for path in self.model_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Benchmark model not found: {missing[0]}")
        if self.tracker not in {"bytetrack", "botsort", "deepocsort"}:
            raise ValueError(f"Unsupported tracker: {self.tracker}")


class VisionBenchmarkRunner:
    """Runs models one at a time so they do not compete for accelerator resources."""

    def __init__(self, detector_factory=VideoDetector) -> None:
        self.detector_factory = detector_factory

    def run(
        self,
        request: VisionBenchmarkRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> list[ModelBenchmarkResult]:
        request.validate()
        annotations = load_replay_jsonl(request.annotation_path)
        if not annotations:
            raise ValueError("Benchmark annotation contains no frames")
        results = []
        for index, model_path in enumerate(request.model_paths):
            if progress is not None:
                progress(index, len(request.model_paths), f"Loading {model_path.name}")
            report, elapsed = self._run_model(request, model_path, annotations, progress)
            results.append(
                result_from_report(
                    report,
                    model_path=model_path,
                    tracker=request.tracker,
                    dataset_version=request.dataset_version,
                    profile="Vision Core",
                    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                    metadata={
                        "video": str(request.video_path),
                        "annotations": str(request.annotation_path),
                        "elapsed_seconds": elapsed,
                        "confidence_threshold": request.confidence_threshold,
                        "detector_imgsz": request.detector_imgsz,
                        "warmup_frames": request.warmup_frames,
                        "model_sha256": _sha256(model_path),
                        "python": platform.python_version(),
                        "platform": platform.platform(),
                        "machine": platform.machine(),
                        "git_commit": _git_commit(),
                    },
                )
            )
        if progress is not None:
            progress(len(request.model_paths), len(request.model_paths), "Complete")
        return results

    def _run_model(
        self,
        request: VisionBenchmarkRequest,
        model_path: Path,
        annotations: list[ReplayFrame],
        progress: ProgressCallback | None,
    ):
        config = InputConfig(
            source_type="video_file",
            video_path=str(request.video_path),
            model_path=str(model_path),
            tracker_name=request.tracker,  # type: ignore[arg-type]
            confidence_threshold=request.confidence_threshold,
            detector_imgsz=request.detector_imgsz,
        )
        detector = self.detector_factory(config)
        started = perf_counter()
        outputs: list[ReplayFrame] = []
        annotation_by_index = {frame.frame_index: frame for frame in annotations}
        max_frame = max(annotation_by_index)
        detector.load_model()
        detector.open_source()
        try:
            if request.warmup_frames > 0:
                warmup_frame = detector.read_frame()
                if warmup_frame is None:
                    raise ValueError("Benchmark video contains no decodable frames")
                for _ in range(request.warmup_frames):
                    detector.track_frame(warmup_frame)
                if not detector.seek_video_frame(0):
                    raise RuntimeError("Unable to rewind video after benchmark warm-up")
            for frame_index in range(max_frame + 1):
                frame = detector.read_frame()
                if frame is None:
                    break
                inference_started = perf_counter()
                predictions = detector.track_frame(frame)
                inference_ms = (perf_counter() - inference_started) * 1000.0
                annotation = annotation_by_index.get(frame_index)
                if annotation is None:
                    continue
                converted = tuple(
                    EvaluationObject(
                        bbox=item.bbox,
                        class_id=item.class_id,
                        confidence=item.confidence,
                        track_id=item.track_id,
                    )
                    for item in predictions
                )
                output = ReplayOutput(
                    detections=converted,
                    command_timestamp_ms=annotation.capture_timestamp_ms + inference_ms,
                )
                outputs.append(
                    replace(annotation, payload=None, dropped=False, recorded_output=output)
                )
                if progress is not None and frame_index % 30 == 0:
                    progress(
                        len(outputs),
                        len(annotations),
                        f"{model_path.name}: frame {frame_index}",
                    )
        finally:
            detector.close()
        if len(outputs) != len(annotations):
            missing = sorted(set(annotation_by_index) - {frame.frame_index for frame in outputs})
            raise ValueError(
                f"Video ended before all annotated frames were evaluated; "
                f"first missing frame: {missing[0] if missing else 'unknown'}"
            )
        return OfflineReplayRunner().run(outputs), perf_counter() - started


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare up to five detection models")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--model", type=Path, action="append", required=True)
    parser.add_argument("--tracker", choices=("bytetrack", "botsort", "deepocsort"), default="botsort")
    parser.add_argument("--dataset-version", default="local-golden-v1")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    request = VisionBenchmarkRequest(
        video_path=args.video,
        annotation_path=args.annotations,
        model_paths=tuple(args.model),
        tracker=args.tracker,
        dataset_version=args.dataset_version,
    )
    results = VisionBenchmarkRunner().run(request)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_results(args.output, results)
    print(json.dumps({"output": str(args.output), "models": len(results)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
