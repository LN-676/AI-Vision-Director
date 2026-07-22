"""Versioned workspace state stored through QSettings."""

from __future__ import annotations

from enum import StrEnum


ORGANIZATION_NAME = "AI Vision Director"
APPLICATION_NAME = "AI Vision Director Qt"
LAYOUT_VERSION = 3
GEOMETRY_KEY = "workspace/geometry"
STATE_KEY = "workspace/windowState"
SPLITTER_KEY = "workspace/monitorSplitter"
VERSION_KEY = "workspace/layoutVersion"
PRESET_KEY = "workspace/preset"
CUSTOM_GEOMETRY_KEY = "workspace/customGeometry"
CUSTOM_STATE_KEY = "workspace/customWindowState"
CUSTOM_SPLITTER_KEY = "workspace/customMonitorSplitter"
SOURCE_KEY = "source/lastType"


class Workspace(StrEnum):
    TRACKING = "Tracking"
    IDENTITY = "Identity"
    PERFORMANCE = "Performance"
