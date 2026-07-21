# Phase 8: WebSocket Components

The application-facing `TrackingWebSocketServer` remains a compatibility façade
and composes five focused components:

- `protocol`: JSON encoding/decoding, versioned tracking messages, motor-status
  parsing, and camera-envelope validation.
- `transport`: WebSocket connection lifecycle and raw `bytes`/`str` delivery.
- `CameraStreamReceiver`: bounded latest-JPEG buffering, decoding, and timing.
- `ControlPublisher`: outbound sequencing and rate limiting.
- `ControlPolicy`: pure CV-state-to-control decisions and remote-control validation.

## Transport boundary

`transport.py` has no imports from core, domain, tracking, or vision packages. It
does not receive a `FrameData`, detection, identity, motor status, or any other CV
domain object. Binary and text callbacks deliver raw wire data upward; connection
callbacks only report client counts. Therefore the transport cannot mutate CV
domain state.

The control policy returns a `FrameControlDecision` containing a wire payload and
an optional projected center. The policy does not write to the supplied frame
object. The compatibility façade may copy that projection into legacy telemetry
state after the policy returns; this happens above the transport boundary.
