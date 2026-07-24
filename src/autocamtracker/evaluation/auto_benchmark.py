"""Annotation-free, repeatable Detection × ReID video benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Callable

from autocamtracker.evaluation.benchmark import (
    MAX_COMPARE_MODELS,
    MAX_SCORE,
    BenchmarkAxes,
    BenchmarkScore,
    ModelBenchmarkResult,
)
from autocamtracker.tracking.crop_quality_assessor import CropQualityAssessor
from autocamtracker.tracking.reid_embedding import (
    ReIDEmbeddingConfig,
    ReIDEmbeddingExtractor,
)
from autocamtracker.vision.detector import VideoDetector
from autocamtracker.vision.scene_cut import SceneCutDetector
from autocamtracker.vision.types import InputConfig


ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class BenchmarkModelPair:
    detection_model: Path
    reid_model: Path

    @property
    def label(self) -> str:
        return f"{self.detection_model.stem} + {self.reid_model.stem}"


@dataclass(frozen=True)
class AutoBenchmarkRequest:
    video_path: Path
    model_pairs: tuple[BenchmarkModelPair, ...]
    tracker: str = "botsort"
    dataset_version: str = "quick-auto-v1"
    rounds: int = 3
    feature_limit: int = 50
    duration_seconds: float = 0.0
    confidence_threshold: float = 0.25
    detector_imgsz: int | None = 640
    warmup_frames: int = 3
    match_threshold: float = 0.72

    def validate(self) -> None:
        if not self.video_path.is_file():
            raise FileNotFoundError(f"Benchmark video not found: {self.video_path}")
        if not 1 <= len(self.model_pairs) <= MAX_COMPARE_MODELS:
            raise ValueError(
                f"Select between 1 and {MAX_COMPARE_MODELS} model combinations"
            )
        for pair in self.model_pairs:
            if not pair.detection_model.is_file():
                raise FileNotFoundError(
                    f"Detection model not found: {pair.detection_model}"
                )
            if not pair.reid_model.is_file():
                raise FileNotFoundError(f"ReID model not found: {pair.reid_model}")
        if self.tracker not in {"bytetrack", "botsort", "deepocsort"}:
            raise ValueError(f"Unsupported tracker: {self.tracker}")
        if not 1 <= self.rounds <= 5:
            raise ValueError("Measured rounds must be between 1 and 5")
        if not 1 <= self.feature_limit <= 500:
            raise ValueError("Feature limit must be between 1 and 500")
        if self.duration_seconds < 0:
            raise ValueError("Duration must be zero (full video) or positive")


class AutoBenchmarkRunner:
    """Runs a proxy benchmark without presenting predictions as ground truth."""

    def __init__(
        self,
        detector_factory=VideoDetector,
        embedding_factory=ReIDEmbeddingExtractor,
        scene_cut_factory=SceneCutDetector,
        quality_assessor: CropQualityAssessor | None = None,
    ) -> None:
        self.detector_factory = detector_factory
        self.embedding_factory = embedding_factory
        self.scene_cut_factory = scene_cut_factory
        self.quality_assessor = quality_assessor or CropQualityAssessor()

    def run(
        self,
        request: AutoBenchmarkRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> list[ModelBenchmarkResult]:
        request.validate()
        total_steps = len(request.model_pairs) * (request.rounds + 1)
        completed = 0
        states: dict[BenchmarkModelPair, dict] = {}
        for pair in request.model_pairs:
            self._progress(
                progress,
                completed,
                total_steps,
                f"{pair.label}: enrolling {request.feature_limit} features",
            )
            encoder = self.embedding_factory(
                ReIDEmbeddingConfig(model_path=str(pair.reid_model))
            )
            if not getattr(encoder, "available", False):
                raise RuntimeError(
                    f"Unable to load ReID model {pair.reid_model.name}: "
                    f"{getattr(encoder, 'error', 'unknown error')}"
                )
            gallery, evaluation_start = self._enroll(request, pair, encoder)
            states[pair] = {
                "encoder": encoder,
                "gallery": gallery,
                "evaluation_start": evaluation_start,
                "rounds": [],
            }
            completed += 1
        for round_index in range(request.rounds):
            ordered_pairs = (
                request.model_pairs
                if round_index % 2 == 0
                else tuple(reversed(request.model_pairs))
            )
            for pair in ordered_pairs:
                self._progress(
                    progress,
                    completed,
                    total_steps,
                    f"{pair.label}: measured round {round_index + 1}/{request.rounds}",
                )
                state = states[pair]
                state["rounds"].append(
                    self._measure_round(
                        request,
                        pair,
                        state["encoder"],
                        state["gallery"],
                        state["evaluation_start"],
                        round_index + 1,
                    )
                )
                completed += 1
        results = [
            self._result(
                request,
                pair,
                states[pair]["gallery"],
                states[pair]["rounds"],
            )
            for pair in request.model_pairs
        ]
        self._progress(progress, total_steps, total_steps, "Complete")
        return results

    def _enroll(self, request, pair, encoder):
        detector = self._detector(request, pair)
        detector.load_model()
        detector.open_source()
        gallery: list[list[float]] = []
        target_track_id = None
        frame_index = -1
        fps = float(detector.get_source_fps() or 30.0)
        sample_interval = max(1, round(fps / 5.0))
        max_frames = self._max_frames(request, fps)
        try:
            self._warm_up(detector, request.warmup_frames)
            while max_frames is None or frame_index + 1 < max_frames:
                frame = detector.read_frame()
                if frame is None:
                    break
                frame_index += 1
                detections = detector.track_frame(frame)
                if target_track_id is None and detections:
                    target_track_id = max(detections, key=_bbox_area).track_id
                target = next(
                    (
                        item
                        for item in detections
                        if item.track_id == target_track_id
                    ),
                    None,
                )
                if (
                    target is None
                    or frame_index % sample_interval
                    or not self.quality_assessor.assess(frame, target.bbox).accepted
                ):
                    continue
                extracted = encoder.extract_batch(frame, [target.bbox]) or []
                if extracted and extracted[0]:
                    gallery.append(extracted[0])
                if len(gallery) >= request.feature_limit:
                    break
        finally:
            detector.close()
        if len(gallery) < request.feature_limit:
            raise ValueError(
                f"{pair.label} collected {len(gallery)}/{request.feature_limit} "
                "usable features. Use a longer enrollment section or lower the limit."
            )
        evaluation_start = frame_index + 1
        if max_frames is not None and evaluation_start >= max_frames:
            raise ValueError(
                f"{pair.label} filled the gallery at the end of the selected duration; "
                "no frames remain for evaluation."
            )
        return gallery, evaluation_start

    def _measure_round(
        self,
        request,
        pair,
        encoder,
        gallery,
        evaluation_start,
        round_number,
    ):
        detector = self._detector(request, pair)
        detector.load_model()
        detector.open_source()
        fps_hint = float(detector.get_source_fps() or 30.0)
        max_frames = self._max_frames(request, fps_hint)
        cut_detector = self.scene_cut_factory()
        frame_index = evaluation_start - 1
        processed = detection_frames = matched_frames = 0
        confidence_values: list[float] = []
        similarity_values: list[float] = []
        latencies: list[float] = []
        stable_links = track_links = 0
        previous_track_id = None
        cut_count = 0
        pending_cut_frame = None
        reacquire_delays: list[float] = []
        shots: list[dict] = []
        shot = _new_shot(0, evaluation_start)
        started = perf_counter()
        try:
            if not detector.seek_video_frame(evaluation_start):
                for _ in range(evaluation_start):
                    if detector.read_frame() is None:
                        break
            while max_frames is None or frame_index + 1 < max_frames:
                frame = detector.read_frame()
                if frame is None:
                    break
                frame_index += 1
                if cut_detector.update(frame):
                    shot["end_frame"] = frame_index - 1
                    shots.append(shot)
                    cut_count += 1
                    shot = _new_shot(cut_count, frame_index)
                    pending_cut_frame = frame_index
                    previous_track_id = None
                inference_started = perf_counter()
                detections = detector.track_frame(frame)
                processed += 1
                shot["frames"] += 1
                if detections:
                    detection_frames += 1
                    shot["detection_frames"] += 1
                    confidence_values.extend(item.confidence for item in detections)
                    shot["confidence_sum"] += fmean(
                        item.confidence for item in detections
                    )
                embeddings = encoder.extract_batch(
                    frame,
                    [item.bbox for item in detections],
                ) or []
                latencies.append((perf_counter() - inference_started) * 1000.0)
                candidates = [
                    (_gallery_similarity(embedding, gallery), detection)
                    for detection, embedding in zip(detections, embeddings)
                    if embedding
                ]
                similarity, target = max(
                    candidates,
                    key=lambda item: item[0],
                    default=(0.0, None),
                )
                similarity_values.append(similarity)
                if target is None or similarity < request.match_threshold:
                    previous_track_id = None
                    continue
                matched_frames += 1
                shot["matched_frames"] += 1
                if target.track_id is not None:
                    shot["track_ids"].add(target.track_id)
                if previous_track_id is not None and target.track_id is not None:
                    track_links += 1
                    stable_links += target.track_id == previous_track_id
                previous_track_id = target.track_id
                if pending_cut_frame is not None:
                    reacquire_delays.append(
                        (frame_index - pending_cut_frame) * 1000.0 / fps_hint
                    )
                    pending_cut_frame = None
        finally:
            detector.close()
        elapsed = perf_counter() - started
        shot["end_frame"] = frame_index
        shots.append(shot)
        if processed == 0:
            raise ValueError(f"{pair.label} has no frames after enrollment")
        detection_coverage = detection_frames / processed
        match_coverage = matched_frames / processed
        mean_confidence = fmean(confidence_values) if confidence_values else 0.0
        mean_similarity = fmean(similarity_values) if similarity_values else 0.0
        detection_proxy = _clamp(
            0.5 * detection_coverage + 0.5 * mean_confidence
        )
        tracking_proxy = (
            stable_links / track_links if track_links else match_coverage
        )
        reacquire_rate = (
            len(reacquire_delays) / cut_count if cut_count else match_coverage
        )
        identity_proxy = _clamp(
            0.4 * match_coverage
            + 0.3 * mean_similarity
            + 0.3 * reacquire_rate
        )
        measured_fps = processed / max(elapsed, 1e-9)
        p50 = _percentile(latencies, 0.50)
        p95 = _percentile(latencies, 0.95)
        p99 = _percentile(latencies, 0.99)
        realtime = _clamp(
            0.4 * _clamp(measured_fps / 30.0)
            + 0.4 * _clamp(1.0 - p95 / 150.0)
            + 0.2
        )
        return {
            "round": round_number,
            "processed_frames": processed,
            "detection_proxy": detection_proxy,
            "tracking_proxy": tracking_proxy,
            "identity_proxy": identity_proxy,
            "realtime": realtime,
            "detection_coverage": detection_coverage,
            "match_coverage": match_coverage,
            "mean_confidence": mean_confidence,
            "mean_similarity": mean_similarity,
            "scene_cuts": cut_count,
            "reacquire_rate": reacquire_rate,
            "reacquire_ms": (
                fmean(reacquire_delays) if reacquire_delays else None
            ),
            "fps": measured_fps,
            "latency_p50_ms": p50,
            "latency_p95_ms": p95,
            "latency_p99_ms": p99,
            "shots": [_finalize_shot(item) for item in shots],
        }

    def _result(self, request, pair, gallery, rounds):
        detection = _mean(rounds, "detection_proxy")
        tracking = _mean(rounds, "tracking_proxy")
        identity = _mean(rounds, "identity_proxy")
        realtime = _mean(rounds, "realtime")
        axes = BenchmarkAxes(
            detection=detection,
            tracking=tracking,
            identity=identity,
            realtime=realtime,
        )
        total = round(MAX_SCORE * fmean(axes.available().values()))
        fps_values = [float(item["fps"]) for item in rounds]
        metrics = {
            "Detection proxy": detection,
            "Tracking proxy": tracking,
            "ReID proxy": identity,
            "Detection coverage": _mean(rounds, "detection_coverage"),
            "ReID match coverage": _mean(rounds, "match_coverage"),
            "Mean confidence": _mean(rounds, "mean_confidence"),
            "Mean similarity": _mean(rounds, "mean_similarity"),
            "Scene cuts": round(_mean(rounds, "scene_cuts")),
            "Proxy reacquire rate": _mean(rounds, "reacquire_rate"),
            "Reacquire time ms": _mean_optional(rounds, "reacquire_ms"),
            "Feature count": len(gallery),
            "Rounds": len(rounds),
            "FPS": fmean(fps_values),
            "FPS std": _population_std(fps_values),
            "Latency p50 ms": _mean(rounds, "latency_p50_ms"),
            "Latency p95 ms": _mean(rounds, "latency_p95_ms"),
            "Latency p99 ms": _mean(rounds, "latency_p99_ms"),
            "Dropped frame rate": 0.0,
        }
        return ModelBenchmarkResult(
            model_name=pair.label,
            model_path=str(pair.detection_model),
            reid_model_path=str(pair.reid_model),
            tracker=request.tracker,
            dataset_version=request.dataset_version,
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            metadata={
                "mode": "quick_auto",
                "accuracy_ground_truth": False,
                "warning": (
                    "Proxy metrics measure consistency and performance, not "
                    "ground-truth identity correctness."
                ),
                "rounds": rounds,
                "shots": _aggregate_shots(rounds),
                "feature_limit": request.feature_limit,
                "duration_seconds": request.duration_seconds,
            },
            metrics=metrics,
            score=BenchmarkScore(
                total=total,
                coverage=axes.coverage,
                axes=axes,
                profile="Quick Auto · proxy",
                safety_passed=True,
            ),
        )

    def _detector(self, request, pair):
        return self.detector_factory(
            InputConfig(
                source_type="video_file",
                video_path=str(request.video_path),
                model_path=str(pair.detection_model),
                tracker_name=request.tracker,
                confidence_threshold=request.confidence_threshold,
                detector_imgsz=request.detector_imgsz,
            )
        )

    @staticmethod
    def _warm_up(detector, count: int) -> None:
        if count <= 0:
            return
        frame = detector.read_frame()
        if frame is None:
            raise ValueError("Benchmark video contains no decodable frames")
        for _ in range(count):
            detector.track_frame(frame)
        if not detector.seek_video_frame(0):
            raise RuntimeError("Unable to rewind video after benchmark warm-up")

    @staticmethod
    def _max_frames(request, fps: float) -> int | None:
        if request.duration_seconds <= 0:
            return None
        return max(1, round(request.duration_seconds * fps))

    @staticmethod
    def _progress(progress, current, total, text) -> None:
        if progress is not None:
            progress(current, total, text)


def _bbox_area(detection) -> float:
    x1, y1, x2, y2 = detection.bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _gallery_similarity(embedding, gallery) -> float:
    return max((_cosine(embedding, feature) for feature in gallery), default=0.0)


def _cosine(first, second) -> float:
    numerator = sum(float(a) * float(b) for a, b in zip(first, second))
    first_norm = sqrt(sum(float(value) ** 2 for value in first))
    second_norm = sqrt(sum(float(value) ** 2 for value in second))
    if first_norm <= 1e-12 or second_norm <= 1e-12:
        return 0.0
    return _clamp(numerator / (first_norm * second_norm))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (
        position - lower
    )


def _mean(rows, key: str) -> float:
    return fmean(float(item[key]) for item in rows)


def _mean_optional(rows, key: str) -> float | None:
    values = [float(item[key]) for item in rows if item[key] is not None]
    return fmean(values) if values else None


def _population_std(values: list[float]) -> float:
    mean = fmean(values)
    return sqrt(fmean((value - mean) ** 2 for value in values))


def _new_shot(shot_id: int, start_frame: int) -> dict:
    return {
        "shot_id": shot_id,
        "start_frame": start_frame,
        "end_frame": start_frame,
        "frames": 0,
        "detection_frames": 0,
        "matched_frames": 0,
        "confidence_sum": 0.0,
        "track_ids": set(),
    }


def _finalize_shot(shot: dict) -> dict:
    frames = max(1, int(shot["frames"]))
    return {
        "shot_id": int(shot["shot_id"]),
        "start_frame": int(shot["start_frame"]),
        "end_frame": int(shot["end_frame"]),
        "frames": int(shot["frames"]),
        "detection_coverage": float(shot["detection_frames"]) / frames,
        "reid_match_coverage": float(shot["matched_frames"]) / frames,
        "mean_confidence": float(shot["confidence_sum"]) / frames,
        "unique_tracks": len(shot["track_ids"]),
    }


def _aggregate_shots(rounds: list[dict]) -> list[dict]:
    shot_ids = sorted(
        {
            int(shot["shot_id"])
            for item in rounds
            for shot in item.get("shots", [])
        }
    )
    aggregated = []
    for shot_id in shot_ids:
        rows = [
            shot
            for item in rounds
            for shot in item.get("shots", [])
            if int(shot["shot_id"]) == shot_id
        ]
        aggregated.append(
            {
                "shot_id": shot_id,
                "start_frame": min(int(item["start_frame"]) for item in rows),
                "end_frame": max(int(item["end_frame"]) for item in rows),
                "frames": round(fmean(float(item["frames"]) for item in rows)),
                "detection_coverage": fmean(
                    float(item["detection_coverage"]) for item in rows
                ),
                "reid_match_coverage": fmean(
                    float(item["reid_match_coverage"]) for item in rows
                ),
                "mean_confidence": fmean(
                    float(item["mean_confidence"]) for item in rows
                ),
                "unique_tracks": round(
                    fmean(float(item["unique_tracks"]) for item in rows)
                ),
            }
        )
    return aggregated
