# Phase 1: Domain Data Contracts

The `autocamtracker.domain` package defines the stable data exchanged between
future pipeline stages:

- `FramePacket`: captured image and source/timing metadata.
- `DetectionBatch`: detector observations for one frame.
- `TrackBatch`: tracker observations for one frame.
- `IdentityState`: long-lived GID state, separate from a temporary LID.
- `TargetState`: selected target state for framing and camera control.
- `CameraCommand`: normalized, transport-independent camera intent.

`BoundingBox`, `Detection`, and `Track` are immutable value objects used by the
six top-level contracts.

## Phase 1 integration rule

The contracts are additive. Existing v1.77 YOLO, ByteTrack/BoT-SORT, GID, and
ReID call sites continue using their current types and behavior. A later phase
may introduce explicit adapters and migrate one boundary at a time, guarded by
characterization and evaluation tests.
