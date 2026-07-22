"""Versioned workspace state stored through QSettings."""

from __future__ import annotations

from enum import StrEnum


ORGANIZATION_NAME = "AI Vision Director"
APPLICATION_NAME = "AI Vision Director Qt"
LAYOUT_VERSION = 2
GEOMETRY_KEY = "workspace/geometry"
STATE_KEY = "workspace/windowState"
VERSION_KEY = "workspace/layoutVersion"
PRESET_KEY = "workspace/preset"


class Workspace(StrEnum):
    TRACKING = "Tracking"
    IDENTITY = "Identity"
    PERFORMANCE = "Performance"
