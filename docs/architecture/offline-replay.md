# Phase 9: Offline Replay and Evaluation

`OfflineReplayRunner` evaluates a deterministic sequence of `ReplayFrame`
records without importing the UI, WebSocket transport, camera device, or a
wall-clock scheduler. It accepts either a processor callable or previously
recorded outputs. Dropped frames never invoke the processor and remain part of
the detection, tracking, and system denominators.

## Input

`run(frames)` accepts typed Python records. `run_jsonl(path)` accepts one JSON
object per line with this shape:

```json
{
  "frame_index": 0,
  "capture_timestamp_ms": 1000.0,
  "ground_truth": [
    {"bbox": [0, 0, 100, 60], "class_id": 2, "identity_id": 7}
  ],
  "dropped": false,
  "output": {
    "detections": [
      {"bbox": [1, 0, 101, 60], "class_id": 2, "confidence": 0.95, "track_id": 12}
    ],
    "command_timestamp_ms": 1024.0,
    "reid": {
      "expected_identity_id": 7,
      "ranked_identity_ids": [7, 3, 9],
      "reacquire_attempted": true,
      "reacquired_identity_id": 7
    },
    "control": {
      "timestamp_ms": 1000.0,
      "error_x": 0.1,
      "error_y": 0.0,
      "command_x": 0.08,
      "command_y": 0.0,
      "target_in_frame": true
    }
  }
}
```

Bounding boxes use `[x1, y1, x2, y2]`. Timestamps and reported latency or
settling time use milliseconds. Control errors and commands use normalized
frame coordinates.

## Metric definitions

- Detection uses class-aware IoU matching. `mAP50` and `mAP50-95` use
  101-point interpolated AP; the latter averages IoU thresholds 0.50 through
  0.95 in 0.05 steps. Precision and recall use IoU 0.50.
- Tracking reports HOTA averaged over IoU thresholds 0.05 through 0.95, global
  IDF1, MOTA, identity switches, and fragmentation.
- ReID reports Rank-1, Rank-5, and mean reciprocal rank as mAP for the current
  single-relevant-identity query model. False reacquire rate is wrong accepted
  identities divided by attempts. Success rate is correct accepted identities
  divided by attempts.
- System FPS is effective processed FPS over capture timestamps. Latency
  percentiles use capture-to-command samples, and dropped frame rate uses all
  replay records.
- Control overshoot is the peak normalized sign reversal relative to the
  initial error. Settling time starts at the first sample after which every
  remaining target is in frame and radial error is within tolerance. Jitter is
  RMS command-vector change. Target-out-of-frame ratio uses all control samples.

## Architectural boundary

The runner consumes evaluation records and returns an immutable report. It
does not mutate CV domain state and does not depend on transport state. A live
pipeline adapter can be supplied as the processor callable without coupling
metric implementations to the production UI or WebSocket lifecycle.

## Compatibility

This phase only adds a new `autocamtracker.evaluation` package. Existing UI,
tracking, persistence, and WebSocket APIs remain unchanged. Recorded datasets
must provide unique frame indexes; invalid boxes or confidence values are
rejected early.
