# AI Vision Director V1.0 Baseline

This repository is the active AI Vision Director monorepo. Development must not
be performed in the archived team repository or one of its old worktrees.

## Source control baseline

- Repository: `git@github.com:LN-676/AI-Vision-Director.git`
- Current branch: `main`
- Current release tag: `v1.0`
- Legacy source tag: `v1.77`
- Legacy source commit: `1d305461615bbd56b1d265bc4e17d354bd32fbe8`
- Archived source repository: `LN-676/AutoCamTracker-team_ver` (read-only)

The V1.77 tag remains the immutable historical snapshot. V1.0 is the first
release using the unified AI Vision Director product name and synchronized
Desktop/iOS version.

## Compatibility boundary

The architecture layers preserve the observable behavior of the existing YOLO
detector, ByteTrack/BoT-SORT adapters, GID manager, ReID implementation, and
DockKit command path. Domain contracts isolate future model and UI replacements
from transport and persistence code.

## V1.0 verification commands

```bash
PYTHONPATH=src python -m unittest discover -s tests
(cd ios/DockKitTester && swift test)
xcodebuild -project ios/DockKitTester/DockKitTester.xcodeproj \
  -scheme DockKitTester -configuration Debug \
  -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build
```

## Repository infrastructure note

Model objects under `code/model/` may use Git LFS. A clone intended for actual
inference must contain the real model bytes rather than LFS pointer files. Local
runtime databases, recordings, telemetry, caches, and test outputs are not part
of the release.
