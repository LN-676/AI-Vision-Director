# Phase 0: v1.0-alpha.1 Baseline

This repository is the active continuation repository. Development must not be
performed in the archived team repository or one of its old worktrees.

## Source control baseline

- Repository: `git@github.com:LN-676/AI-Vision-Director.git`
- Branch: `architecture/domain-contracts-v1.0-alpha.1`
- Base tag: `v1.0-alpha.1`
- Base commit: `1d305461615bbd56b1d265bc4e17d354bd32fbe8`
- Archived source repository: `LN-676/AutoCamTracker-team_ver` (read-only)

## Compatibility boundary

The first architecture phases preserve the observable results of the existing
YOLO detector, ByteTrack/BoT-SORT adapter, GID manager, and ReID implementation.
New domain contracts are introduced alongside the working pipeline before any
production call site is migrated.

## Baseline verification

The baseline was verified on 2026-07-21 with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
(cd ios/DockKitTester && swift test)
```

Results:

- Python: 39 passed
- Swift: 19 passed
- Total: 58 passed

## Repository infrastructure note

The continuation repository currently returns HTTP 404 for the ten Git LFS
model objects referenced by v1.0-alpha.1. The local checkout was completed from the
archived read-only worktree only after each model's SHA-256 was verified against
its committed LFS object ID. No model bytes or model configuration were changed.
The missing remote LFS objects should be repaired separately from architecture
work.
