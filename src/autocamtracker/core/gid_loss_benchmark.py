"""Compatibility imports for the Phase 10 GID loss benchmark.

New code should import from :mod:`autocamtracker.evaluation.gid_loss`.
"""

from autocamtracker.evaluation.gid_loss import (
    DEFAULT_MANIFEST,
    GIDLossBenchmarkReport,
    GIDLossBenchmarkRunner,
    GIDLossMetrics,
    GIDLossScenarioReport,
    GIDLossScenarioSpec,
    GIDLossSpec,
    GIDLossThresholds,
    REQUIRED_SCENARIOS,
    evaluate_gid_loss,
    load_gid_loss_spec,
)

# Phase 5 callers used this loader name. Keep it as an alias while returning
# the stricter Phase 10 specification.
load_gid_loss_benchmark = load_gid_loss_spec
GIDLossBenchmark = GIDLossSpec
GIDLossScenario = GIDLossScenarioSpec

__all__ = [
    "DEFAULT_MANIFEST",
    "GIDLossBenchmark",
    "GIDLossBenchmarkReport",
    "GIDLossBenchmarkRunner",
    "GIDLossMetrics",
    "GIDLossScenario",
    "GIDLossScenarioReport",
    "GIDLossScenarioSpec",
    "GIDLossSpec",
    "GIDLossThresholds",
    "REQUIRED_SCENARIOS",
    "evaluate_gid_loss",
    "load_gid_loss_benchmark",
    "load_gid_loss_spec",
]
