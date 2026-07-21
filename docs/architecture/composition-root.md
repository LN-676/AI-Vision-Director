# Phase 4: Single Composition Root

`autocamtracker.bootstrap` is the only production module that constructs the
desktop object graph. It creates and connects:

- `TrackingApplication`
- detector store, identity services, scene-cut handling, reframer, and pipeline
- telemetry and performance evaluation
- WebSocket infrastructure and its thread-safe UI queues
- track-shot and identity-session state
- the Tk root and `AutoCamTrackerApp`

`AutoCamTrackerApp` requires an `AppDependencies` bundle and performs no fallback
service construction. `main.py` is now a thin entry-point adapter that calls
`bootstrap.run()`. The former standalone entry point in `video_pipeline.py` was
removed.

Tests enforce that the concrete top-level constructors do not appear outside
`bootstrap.py`, preventing accidental secondary desktop composition roots. The
isolated `core/self_test.py` diagnostic fixtures and `Reframer`'s internal
default value config are explicitly excluded from this desktop-runtime rule.
