"""Stable domain data contracts for the AI Vision Director pipeline."""

from autocamtracker.domain.contracts import (
    BoundingBox,
    CameraCommand,
    Detection,
    DetectionBatch,
    FramePacket,
    IdentityState,
    TargetState,
    Track,
    TrackBatch,
)

__all__ = [
    "BoundingBox",
    "CameraCommand",
    "Detection",
    "DetectionBatch",
    "FramePacket",
    "IdentityState",
    "TargetState",
    "Track",
    "TrackBatch",
]
