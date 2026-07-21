# Phase 11: Auditable Identity Decisions

Every selected-identity decision now emits a typed `IdentityDecision`. The
contract is shared by manual selection/linking, stored-GID lookup, tracker
continuity, gallery ReID, legacy visual matching, predictive coasting, camera
cuts, searching, and terminal loss.

```json
{
  "reason_code": "GALLERY_PENDING_CONFIRMATION",
  "accepted": false,
  "source": "gallery_reid",
  "score": 0.78,
  "sub_scores": {
    "feature_score": 0.78,
    "second_best_score": 0.61,
    "score_margin": 0.17,
    "low_score_threshold": 0.58,
    "min_score_threshold": 0.72,
    "high_score_threshold": 0.84,
    "required_margin": 0.08,
    "detection_count": 3.0,
    "spatial_candidate_count": 2.0,
    "confirmation_count": 1.0,
    "confirmation_required": 3.0
  },
  "candidate_track_id": null
}
```

## Output rules

- `reason_code` is a stable `IdentityReasonCode` enum value. UI text must not
  be used as an evaluation key.
- `accepted` states whether that individual decision accepted an association
  or safe predicted target.
- `source` identifies the decision family, not a display label.
- `score` is the decision's primary score. Non-ranked state transitions use a
  deterministic value such as zero or the remaining coasting confidence.
- `sub_scores` contains every contributing raw score, threshold, margin,
  confirmation count, and safety factor available to that decision.
- `candidate_track_id` carries the chosen LID when one was accepted or is
  otherwise available.

`GlobalIdentityManager.identity_decisions` contains all decisions attempted in
order for the current operation/frame. This is important when gallery ReID is
unavailable, legacy matching also fails, and motion coasting is finally
selected. `last_identity_decision` is the final outcome convenience view.

## Reason-code families

- Manual: `MANUAL_SELECT_TRANSIENT`, `MANUAL_SELECT_NEW_GID`,
  `MANUAL_SELECT_EXISTING_GID`, `MANUAL_LINK`, and
  `MANUAL_LINK_GID_NOT_FOUND`.
- Stored GID: `STORED_GID_NOT_FOUND`, `STORED_REID_CONFIRMED`,
  `STORED_ACTIVE_TRACK_PRESERVED`, `STORED_GID_SEARCHING`.
- Gallery: `GALLERY_UNAVAILABLE`, `GALLERY_NO_CANDIDATE`,
  `GALLERY_LOW_SCORE`, `GALLERY_AMBIGUOUS`,
  `GALLERY_BELOW_THRESHOLD`, `GALLERY_PENDING_CONFIRMATION`,
  `GALLERY_HIGH_CONFIDENCE`, `GALLERY_CONFIRMED`.
- Legacy visual matcher: `LEGACY_NO_CANDIDATE`, `LEGACY_LOW_SCORE`,
  `LEGACY_AMBIGUOUS`, `LEGACY_PENDING_CONFIRMATION`, `LEGACY_CONFIRMED`.
- Runtime state: `CURRENT_TRACK_MATCH`, `COASTING_PREDICTION`,
  `CAMERA_CUT`, `SEARCHING_NO_MATCH`, `SEARCHING_CANDIDATE`,
  `LOST_MAX_FRAMES`, `IDLE_NO_IDENTITY`, `RESET`.

## Consumers

The final decision and ordered decision list are attached to `FrameData`.
Frame telemetry writes the final reason/score/sub-scores plus the full list.
The desktop-state payload exposes the final reason and sub-scores. Tracking
messages sent to iOS include `identity_reason_code`, `identity_score`, and
`identity_sub_scores`; older clients can ignore these additive fields.

Phase 9/10 offline replay can therefore capture exact production decisions
without reconstructing them from lifecycle status strings or aggregate ReID
scores.
