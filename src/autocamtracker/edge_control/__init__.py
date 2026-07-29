"""Local-first Edge control plane for the tablet remote MVP."""

from autocamtracker.edge_control.api import EdgeControlSettings, install_edge_control_routes
from autocamtracker.edge_control.repository import EdgeControlRepository, SQLiteEdgeControlRepository

__all__ = [
    "EdgeControlRepository",
    "EdgeControlSettings",
    "SQLiteEdgeControlRepository",
    "install_edge_control_routes",
]
