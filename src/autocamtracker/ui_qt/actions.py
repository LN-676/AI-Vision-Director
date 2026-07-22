"""Shared Qt actions and workspace shortcuts."""

from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup, QKeySequence

from autocamtracker.ui_qt.state import Workspace


def create_workspace_actions(parent, callback) -> dict[Workspace, QAction]:
    group = QActionGroup(parent)
    group.setExclusive(True)
    actions: dict[Workspace, QAction] = {}
    shortcuts = {
        Workspace.TRACKING: QKeySequence("Ctrl+1"),
        Workspace.IDENTITY: QKeySequence("Ctrl+2"),
        Workspace.PERFORMANCE: QKeySequence("Ctrl+3"),
    }
    for workspace in Workspace:
        action = QAction(workspace.value, parent)
        action.setCheckable(True)
        action.setShortcut(shortcuts[workspace])
        action.triggered.connect(lambda checked=False, item=workspace: callback(item))
        group.addAction(action)
        actions[workspace] = action
    return actions
