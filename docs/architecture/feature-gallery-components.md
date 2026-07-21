# Phase 6: Feature Gallery Components

`FeatureGallery` remains the stable API used by the UI, identity manager, and
automatic sampler. Its former storage, model, matching, and policy logic is now
composed from six focused components:

- `CropQualityAssessor`: validates crops and encodes accepted crop previews.
- `EmbeddingEncoder`: owns ReID model lifecycle, batch encoding, and track cache.
- `FeatureRepository`: owns the SQLite schema and feature persistence queries.
- `VectorIndex`: caches stored vectors and performs top-k similarity search.
- `GalleryPolicy`: owns duplicate thresholds, match thresholds, and gallery limits.
- `IdentityMatcher`: ranks detections against a vehicle's master features.

The façade preserves existing enrollment, deletion, summary, and matching calls.
This lets future storage or vector backends be replaced without coupling them to
Tkinter or identity state transitions.
