# Phase 10: GID Loss Benchmark

Phase 10 extends the deterministic Phase 9 replay boundary with a versioned
acceptance benchmark for global vehicle identity (GID) continuity. The suite
contains exactly these 14 stress categories:

1. occlusion
2. vehicle crossing
3. fast lateral motion
4. re-entry
5. same color
6. same vehicle model
7. similar livery
8. fast camera pan
9. zoom change
10. motion blur
11. backlight
12. low light
13. far distance
14. scene cut

The canonical manifest is `evaluation/gid_loss_scenarios.json`. Large replay
files remain outside Git and are placed under `evaluation/gid_loss_replays/`.
The manifest is the source of truth for benchmark version, dataset version,
file names, minimum frame counts, and acceptance thresholds.

## Frame annotation

Each scenario is a Phase 9 JSONL replay. In addition to any detection, ReID,
system, or control data, every record must contain `output.gid`:

```json
{
  "frame_index": 42,
  "capture_timestamp_ms": 1400.0,
  "output": {
    "gid": {
      "expected_identity_id": 7,
      "assigned_identity_id": 7,
      "target_visible": true,
      "motor_safe": true
    }
  }
}
```

- `expected_identity_id` is the single selected ground-truth GID for the
  entire scenario.
- `assigned_identity_id` is the GID emitted by the system, or `null` when the
  target is unlocked.
- `target_visible` excludes fully out-of-frame or fully absent frames from the
  lock-rate denominator. Visibility transitions still open a reacquire event.
- `motor_safe` is false if that frame commands the camera from a wrong or
  otherwise unsafe target lock. It is evaluated even while the target is not
  visible.

Every frame needs the annotation. Missing replay files, missing annotations,
duplicate frame indexes, mixed expected GIDs, and undersized scenarios are
hard dataset errors rather than silently degraded scores.

## Metrics and pass criteria

- GID lock rate: correctly assigned visible frames / visible frames.
- Maximum consecutive lost frames: longest visible run without the expected
  GID. Fully invisible frames reset this streak.
- ID switches: entries into a wrong non-null GID assignment. A persistent
  wrong assignment counts once; changing from one wrong GID to another counts
  again.
- Median reacquire frames: median visible lost-frame count between a prior
  lock (or exit after a prior lock) and the next correct lock. Immediate
  re-entry lock is zero frames. Scenarios without a completed reacquire event
  report zero; unresolved losses remain penalized by lock rate and max loss.
- Motor unsafe frames: all annotations with `motor_safe=false`.

The default Phase 10 v1 gates are lock rate at least 0.90, at most 12
consecutive lost frames, zero ID switches, median reacquire at most 8 frames,
and zero unsafe motor frames. Each scenario is checked independently. The
overall suite passes only if all 14 scenarios pass.

## Running the benchmark

After installing the project in editable mode:

```bash
gid-loss-benchmark \
  --manifest evaluation/gid_loss_scenarios.json \
  --output outputs/gid_loss_report.json
```

The process exits with code 0 only when the full suite passes, code 1 when
metrics fail, and raises a dataset error when inputs are incomplete. Omitting
`--output` prints the machine-readable JSON report to stdout. This makes the
same command suitable for local regression checks and CI acceptance gates.

## Architectural boundary

The benchmark consumes recorded `ReplayFrame` data and never imports the UI,
camera, WebSocket transport, or wall-clock scheduler. Production code only
needs to export the four frame-level GID fields. Threshold policy and dataset
composition remain versioned outside the tracking implementation.
