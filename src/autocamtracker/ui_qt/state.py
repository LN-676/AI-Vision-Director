"""Versioned workspace state stored through QSettings."""

from __future__ import annotations

from enum import StrEnum


ORGANIZATION_NAME = "AI Vision Director"
APPLICATION_NAME = "AI Vision Director Qt"
LAYOUT_VERSION = 6
GEOMETRY_KEY = "workspace/geometry"
WINDOW_SIZE_KEY = "workspace/windowSize"
STATE_KEY = "workspace/windowState"
SPLITTER_KEY = "workspace/monitorSplitter"
SPLITTER_SIZES_KEY = "workspace/monitorSplitterSizes"
VERSION_KEY = "workspace/layoutVersion"
PRESET_KEY = "workspace/preset"
CUSTOM_GEOMETRY_KEY = "workspace/customGeometry"
CUSTOM_WINDOW_SIZE_KEY = "workspace/customWindowSize"
CUSTOM_STATE_KEY = "workspace/customWindowState"
CUSTOM_SPLITTER_KEY = "workspace/customMonitorSplitter"
CUSTOM_SPLITTER_SIZES_KEY = "workspace/customMonitorSplitterSizes"
SOURCE_KEY = "source/lastType"

# Captured from the approved production layout:
# - Before/After monitors across the upper center
# - Diagnostics across the lower center
# - Vehicle Database at upper right
# - Source/Models/Track Shot/Tracking tabbed at lower right, with Models selected
DEFAULT_GEOMETRY_BASE64 = (
    "AdnQywADAAAAAABYAAAALQAABYoAAAOGAAAAWAAAAEkAAAWKAAADhgAAAAAAAAAABegA"
    "AABYAAAASQAABYoAAAOG"
)
DEFAULT_SPLITTER_BASE64 = "AAAA/wAAAAEAAAACAAABTgAAAU4AAAAADAEAAAABAA=="
DEFAULT_STATE_BASE64 = (
    "AAAA/wAAAAX9AAAAAgAAAAEAAAEyAAABVPwCAAAAAvsAAAAqAGQAbwBjAGsALgB2AGUA"
    "aABpAGMAbABlAF8AZABhAHQAYQBiAGEAcwBlAQAAABgAAAFUAAAA/wD////7AAAAHABk"
    "AG8AYwBrAC4AYgBlAG4AYwBoAG0AYQByAGsAAAABIwAAAaAAAAOpAP///wAAAAMAAAUz"
    "AAABq/wBAAAAAvwAAAAAAAAD9QAAAGIA////+gAAAAEBAAAAAvsAAAAgAGQAbwBjAGsA"
    "LgBwAGUAcgBmAG8AcgBtAGEAbgBjAGUAAAAAAP////8AAABiAP////sAAAAgAGQAbwBj"
    "AGsALgBkAGkAYQBnAG4AbwBzAHQAaQBjAHMBAAAAAP////8AAABiAP////wAAAQBAAAB"
    "MgAAATIA////+gAAAAECAAAABPsAAAAWAGQAbwBjAGsALgBzAG8AdQByAGMAZQEAAAAA"
    "/////wAAATEA////+wAAABYAZABvAGMAawAuAG0AbwBkAGUAbABzAQAAAAD/////AAAB"
    "lgD////7AAAAHgBkAG8AYwBrAC4AdAByAGEAYwBrAF8AcwBoAG8AdAEAAAAA/////wAA"
    "AIQA////+wAAABoAZABvAGMAawAuAHQAcgBhAGMAawBpAG4AZwEAAAI1AAAA7gAAAO4A"
    "////AAAD9QAAAVQAAAAEAAAABAAAAAgAAAAI/AAAAAEAAAACAAAAAQAAABoAdABvAG8A"
    "bABiAGEAcgAuAHAAYQBnAGUAcwEAAAAA/////wAAAAAAAAAA"
)


class Workspace(StrEnum):
    TRACKING = "Tracking"
    IDENTITY = "Identity"
    PERFORMANCE = "Performance"
    BENCHMARK = "Benchmark"
