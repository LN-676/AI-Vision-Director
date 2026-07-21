# Phase 3: Application Layer

The Tkinter delivery layer now starts and drives tracking through application
use cases instead of constructing CV runtime objects itself.

## Boundaries

- `TrackingApplication` is the composition root for detection storage, identity,
  scene-cut handling, reframing, and the frame pipeline.
- `TrackingSession` owns source lifecycle, detector/worker lifecycle, asynchronous
  frame requests, synchronous rendering, seek/skip, and framing configuration.
- Tkinter owns widgets, scheduling with `root.after`, dialogs, and view rendering.

The UI package no longer imports `VideoDetector`, `PipelineProcessor`, or
`TrackingWorker`. Existing identity-panel interactions use transitional service
aliases supplied by `TrackingApplication`; moving those commands into dedicated
identity use cases can therefore happen incrementally without changing v1.77 CV
results.

## Compatibility

The application layer delegates to the existing Phase 2 `VideoDetector` façade
and the existing pipeline processor/worker. No detector, tracker, GID, or ReID
algorithm was replaced or retuned.
