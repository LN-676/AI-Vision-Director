# Phase 5 identity component boundaries

`GlobalIdentityManager` remains the compatibility façade used by the V1.0 UI,
pipeline, and self-test. Its former responsibilities are delegated to five
independently testable components:

- `IdentityStateMachine`: canonical selected-identity lifecycle.
- `IdentityMatcher`: unchanged color, size, motion, and current-track matching.
- `ReacquisitionPolicy`: unchanged gallery thresholds, margin, spatial corridor,
  and multi-frame confirmation.
- `TrackIdentityMapper`: local track/GID association and identity updates.
- `MotorSafetyPolicy`: unchanged prediction and motor-enable safety rules.

The canonical lifecycle is `LOCKED`, `COASTING`, `SEARCHING`, `CANDIDATE`,
`CONFIRMED`, or `LOST`. The façade deliberately retains legacy lowercase status
strings such as `tracking`, `coasting`, and `camera_cut` at the UI/API boundary.
This prevents a Phase 5 architecture change from altering CV, ReID, telemetry,
or motor-command results.

Production construction and injection of all five components occurs in
`bootstrap.py`. Constructor defaults remain only for backwards-compatible unit
and diagnostic use.
