# Phase 2: Vision Backend Split

`VideoDetector` remains the compatibility façade used by the desktop pipeline,
but it no longer implements all three responsibilities itself:

- `FrameSource` owns opening, reading, seeking, skipping, and closing frame input.
- `DetectorBackend` owns model loading and native detector inference.
- `TrackerBackend` owns local track assignment, tracker configuration, and reset.

The default composition is `ConfiguredFrameSource` +
`UltralyticsDetectorBackend` + either `UltralyticsTrackerBackend` or
`DeepOcSortTrackerBackend`.

## Algorithm compatibility

- ByteTrack and BoT-SORT still call Ultralytics `model.track` with `persist=True`
  and the same confidence, IoU, image-size, and generated tracker configuration.
- Deep OC-SORT still calls YOLO `model.predict`, applies the same vehicle and
  confidence filtering, and passes the same neutral detections to
  `DeepOcSortAdapter.update`.
- `TrackedDetection` remains the production output type, and all existing
  `VideoDetector` entry points remain available through delegation.

The new boundaries are injectable so later evaluation work can replace one
stage at a time without coupling model experiments to input or tracker changes.
