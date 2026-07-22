"""Modular dock panel widgets."""

from autocamtracker.ui_qt.panels.diagnostics_panel import DiagnosticsPanel
from autocamtracker.ui_qt.panels.performance_panel import PerformancePanel
from autocamtracker.ui_qt.panels.playback_panel import PlaybackPanel
from autocamtracker.ui_qt.panels.reid_panel import ReIDPanel
from autocamtracker.ui_qt.panels.source_panel import SourcePanel
from autocamtracker.ui_qt.panels.track_shot_panel import TrackShotPanel
from autocamtracker.ui_qt.panels.tracking_panel import TrackingPanel
from autocamtracker.ui_qt.panels.vehicle_database_panel import VehicleDatabasePanel

__all__ = [
    "DiagnosticsPanel",
    "PerformancePanel",
    "PlaybackPanel",
    "ReIDPanel",
    "SourcePanel",
    "TrackShotPanel",
    "TrackingPanel",
    "VehicleDatabasePanel",
]
