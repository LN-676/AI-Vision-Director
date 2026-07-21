# Phase 12: Gallery Contamination Prevention

Phase 12 makes every gallery mutation conditional, traceable, and reversible.
The rule is enforced inside `FeatureGallery`, so UI, automation, tests, and
future callers cannot bypass it by skipping an upstream sampler check.

## High-confidence LOCKED gate

Every `add_master_feature`, `add_pending_feature`, `add_candidate_feature`, or
JPG import must provide a `GalleryWriteContext`. A write is rejected before
crop processing or embedding inference unless all conditions hold:

- identity lifecycle state is exactly `LOCKED`;
- the Phase 11 identity decision was accepted;
- primary identity score is at least `0.84`;
- the identity is motor-safe to track;
- provenance GID equals the destination GID;
- when the detection has an LID, provenance LID equals that detection LID.

`CONFIRMED`, `CANDIDATE`, `COASTING`, `SEARCHING`, camera-cut, and lost states
cannot update any gallery. A high-confidence gallery reacquisition first moves
through `CONFIRMED`; a subsequent tracker-continuity frame moves it to
`LOCKED`, after which sampling becomes eligible.

`GalleryWriteContext.from_identity_manager(...)` is the production adapter.
Automatic sampling uses source `auto_feature_sampler`; the one-photo UI uses
`manual_feature_add`. Missing context is a hard rejection rather than a
trusted default.

## Embedding provenance

Every newly stored embedding receives a unique `write_id` and a dedicated
`provenance_json` record containing:

- write source and capture timestamp;
- GID, LID, detection frame, class, confidence, and detection LID;
- identity lifecycle state;
- Phase 11 reason code, primary score, and every identity sub-score;
- decision acceptance and motor-safety flags;
- gallery type, crop quality, duplicate score, and ReID model path.

`FeatureRepository.insert` rejects incomplete provenance. SQLite also has an
insert trigger requiring valid provenance JSON with a `write_id`, protecting
callers that attempt raw inserts. During schema migration, pre-Phase-12 rows
receive explicit `legacy_migration` provenance instead of remaining
unattributed.

Provenance is returned by `feature_snapshots` and displayed in the Master
snapshot panel as reason code plus identity score.

## Rollback

Rollback is a soft, audited operation:

```python
result = gallery.rollback_write(
    write_id,
    reason="suspected contamination",
    actor="operator@example",
)
```

`rollback_features` supports a reviewed set of feature IDs and optional GID
scope. Rolled-back rows remain in SQLite with timestamp and reason, but
`stored_features`, vector search, gallery counts, class voting, previews, and
normal snapshots exclude them immediately. The vector index is invalidated
after rollback.

Every rollback creates a `gallery_rollback_events` record. Call
`gallery.rollback_events()` to audit actor, reason, timestamp, and affected
feature IDs. `feature_snapshots(..., include_rolled_back=True)` exposes the
inactive evidence for investigation.

Automatic master-limit pruning now uses the same audited soft-rollback path.
The desktop snapshot management action also performs rollback instead of
permanent deletion. The legacy destructive delete API remains available only
for explicit vehicle/data lifecycle operations.
