# Versioning Policy

AI Vision Director uses one product release identity expressed in the native
format required by each ecosystem. Protocol and data-schema versions are
managed independently and do not change just because the product version
changes.

## Current product version

| Surface | Value | Reason |
| --- | --- | --- |
| Human-facing UI and documentation | `3.0.0 Beta 2` | Readable product label |
| Python package | `3.0.0b2` | PEP 440 prerelease syntax |
| npm package | `3.0.0-beta.2` | Semantic Versioning prerelease syntax |
| Git tag | `v3.0.0-beta.2` | Lowercase, tool-friendly release tag |
| GitHub Release title | `AI Vision Director 3.0.0 Beta 2` | Human-readable release name |
| iOS Marketing Version | `3.0.0` | Numeric Apple bundle version |
| iOS build number | `3003` | Monotonically increasing build identifier |

The Git tag and GitHub Release values describe the naming convention for the
next release operation. They do not claim that the tag or Release already
exists.

## Independent compatibility versions

- WebSocket contract: `1.0`
- Benchmark/result schema versions: maintained by each schema
- API/OpenAPI document version: SemVer product form unless the schema declares
  a separate compatibility version
- SQLite migrations and cache formats: governed by their own compatibility
  rules

A product release may change without changing these compatibility versions.
Conversely, a breaking protocol or schema change must be versioned explicitly
even if the product release also changes.

## Rules for future releases

1. Choose the next SemVer product version before updating code.
2. Update the Python, npm, iOS display, API, and documentation representations
   in the same pull request.
3. Keep iOS Marketing Version numeric and increment the build number for every
   submitted build.
4. Create lowercase tags in the form `vMAJOR.MINOR.PATCH` or
   `vMAJOR.MINOR.PATCH-prerelease.N`.
5. Mark alpha, beta, and release-candidate GitHub Releases as pre-releases.
6. Do not rename historical tags. Apply this convention going forward.
7. Do not describe a version as a GitHub Release until the corresponding tag
   and Release have actually been published.
