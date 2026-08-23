# Secret audit

Last audited: 2026-08-23

## Scope

- The checked-out files, including ignored build output.
- Every reachable commit on all local branches and tags.
- Suspicious filenames such as `.env`, private keys, signing files, service-account
  files, credential files, and mobile provisioning profiles.

The audit used Gitleaks 8.30.1 with redacted output. Secret values are never
copied into this report.

## Result

No active password, API credential, cloud access key, signing key, or private
key was found in the current repository or reachable Git history.

Twelve Git-history matches were manually reviewed and classified as false
positives:

- two revisions of iOS `UserDefaults` record identifiers;
- two copies of a public documentation-image download token in vendored README
  content; and
- eight duplicate matches from expired 2022 GitHub release-asset signed URLs in
  vendored notebook output.

The ignored local Dashboard build directory also contained two generated copies
of the same non-secret `UserDefaults` identifier. Generated output is excluded
from Git and is not part of the repository history.

The audited historical fingerprints are recorded in `.gitleaksignore`, with the
reason documented beside the entries. The current Swift identifiers were also
renamed so they cannot be confused with cryptographic keys.

Because no real credential was found, there was no credential that could be
revoked or rotated. Rewriting every commit and tag for non-secret scanner false
positives would add recovery and collaboration risk without improving account
security.

## Ongoing controls

- `.env` files, secret directories, signing artifacts, model binaries, outputs,
  and infrastructure variable files remain ignored.
- The CI workflow runs a redacted secret scan on pushes and pull requests.
- Real credentials must be provided through environment variables, file-backed
  secrets, or GitHub Actions secrets. They must never be committed.
- If a real credential is ever detected, revoke or rotate it first, then remove
  it from history and coordinate the history rewrite with every clone owner.
