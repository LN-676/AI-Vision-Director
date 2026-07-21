"""Offline evaluation API for AI_Vison_Director."""

from autocamtracker.evaluation.control import ControlMetrics, evaluate_control
from autocamtracker.evaluation.detection import DetectionMetrics, evaluate_detection
from autocamtracker.evaluation.models import (
    ControlObservation,
    EvaluationObject,
    FrameEvaluation,
    ReIDObservation,
    ReplayFrame,
    ReplayOutput,
)
from autocamtracker.evaluation.offline_replay import OfflineReplayReport, OfflineReplayRunner, load_replay_jsonl
from autocamtracker.evaluation.reid import ReIDMetrics, evaluate_reid
from autocamtracker.evaluation.system import SystemMetrics, SystemSample, evaluate_system
from autocamtracker.evaluation.tracking import TrackingMetrics, evaluate_tracking

__all__ = [
    "ControlMetrics", "ControlObservation", "DetectionMetrics", "EvaluationObject", "FrameEvaluation",
    "OfflineReplayReport", "OfflineReplayRunner", "ReIDMetrics", "ReIDObservation", "ReplayFrame",
    "ReplayOutput", "SystemMetrics", "SystemSample", "TrackingMetrics", "evaluate_control",
    "evaluate_detection", "evaluate_reid", "evaluate_system", "evaluate_tracking", "load_replay_jsonl",
]
