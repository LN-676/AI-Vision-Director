"""COCO and MOTChallenge interchange formats for official evaluators."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Iterable

from autocamtracker.evaluation.models import ReplayFrame


def export_coco(
    frames: Iterable[ReplayFrame],
    *,
    ground_truth_path: Path | str,
    predictions_path: Path | str,
) -> None:
    ordered = tuple(frames)
    categories = sorted(
        {
            item.class_id
            for frame in ordered
            for item in (*frame.ground_truth, *(frame.recorded_output.detections if frame.recorded_output else ()))
        }
    )
    images = [{"id": frame.frame_index, "file_name": f"{frame.frame_index:06d}.jpg"} for frame in ordered]
    annotations = []
    predictions = []
    annotation_id = 1
    for frame in ordered:
        for item in frame.ground_truth:
            x1, y1, x2, y2 = item.bbox
            width, height = x2 - x1, y2 - y1
            annotations.append(
                {
                    "id": annotation_id,
                    "image_id": frame.frame_index,
                    "category_id": item.class_id,
                    "bbox": [x1, y1, width, height],
                    "area": width * height,
                    "iscrowd": 0,
                }
            )
            annotation_id += 1
        if frame.recorded_output is not None:
            for item in frame.recorded_output.detections:
                x1, y1, x2, y2 = item.bbox
                predictions.append(
                    {
                        "image_id": frame.frame_index,
                        "category_id": item.class_id,
                        "bbox": [x1, y1, x2 - x1, y2 - y1],
                        "score": item.confidence,
                    }
                )
    ground_truth = {
        "info": {"description": "AI Vision Director benchmark export"},
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": [{"id": class_id, "name": str(class_id)} for class_id in categories],
    }
    Path(ground_truth_path).write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")
    Path(predictions_path).write_text(json.dumps(predictions, indent=2), encoding="utf-8")


def export_mot_challenge(
    frames: Iterable[ReplayFrame],
    *,
    ground_truth_path: Path | str,
    predictions_path: Path | str,
) -> None:
    ground_truth_lines = []
    prediction_lines = []
    for frame in sorted(frames, key=lambda item: item.frame_index):
        mot_frame = frame.frame_index + 1
        for item in frame.ground_truth:
            if item.identity_id is None:
                continue
            x1, y1, x2, y2 = item.bbox
            ground_truth_lines.append(
                f"{mot_frame},{item.identity_id},{x1:.3f},{y1:.3f},"
                f"{x2 - x1:.3f},{y2 - y1:.3f},1,{item.class_id},1"
            )
        if frame.recorded_output is not None:
            for item in frame.recorded_output.detections:
                if item.track_id is None:
                    continue
                x1, y1, x2, y2 = item.bbox
                prediction_lines.append(
                    f"{mot_frame},{item.track_id},{x1:.3f},{y1:.3f},"
                    f"{x2 - x1:.3f},{y2 - y1:.3f},{item.confidence:.6f},-1,-1,-1"
                )
    Path(ground_truth_path).write_text("\n".join(ground_truth_lines) + "\n", encoding="utf-8")
    Path(predictions_path).write_text("\n".join(prediction_lines) + "\n", encoding="utf-8")


def run_official_coco_eval(
    ground_truth_path: Path | str,
    predictions_path: Path | str,
) -> dict[str, float]:
    """Run pycocotools when installed; keep it optional for the desktop runtime."""

    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except ImportError as exc:
        raise RuntimeError(
            "Official COCO evaluation requires pycocotools. "
            "Install the benchmark extra before publishing COCO scores."
        ) from exc
    ground_truth = COCO(str(ground_truth_path))
    predictions = ground_truth.loadRes(str(predictions_path))
    evaluator = COCOeval(ground_truth, predictions, "bbox")
    evaluator.evaluate()
    evaluator.accumulate()
    evaluator.summarize()
    return {
        "AP50-95": float(evaluator.stats[0]),
        "AP50": float(evaluator.stats[1]),
        "AP75": float(evaluator.stats[2]),
        "AP-small": float(evaluator.stats[3]),
        "AP-medium": float(evaluator.stats[4]),
        "AP-large": float(evaluator.stats[5]),
    }


def run_official_trackeval(
    trackeval_root: Path | str,
    *,
    benchmark: str,
    split: str,
    ground_truth_root: Path | str,
    trackers_root: Path | str,
    tracker_name: str,
) -> subprocess.CompletedProcess[str]:
    """Invoke the official TrackEval MOTChallenge entry point."""

    root = Path(trackeval_root)
    script = root / "scripts" / "run_mot_challenge.py"
    if not script.is_file():
        raise FileNotFoundError(f"TrackEval runner not found: {script}")
    return subprocess.run(
        [
            sys.executable,
            str(script),
            "--BENCHMARK",
            benchmark,
            "--SPLIT_TO_EVAL",
            split,
            "--GT_FOLDER",
            str(ground_truth_root),
            "--TRACKERS_FOLDER",
            str(trackers_root),
            "--TRACKERS_TO_EVAL",
            tracker_name,
            "--METRICS",
            "HOTA",
            "CLEAR",
            "Identity",
            "--DO_PREPROC",
            "False",
            "--USE_PARALLEL",
            "False",
        ],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
