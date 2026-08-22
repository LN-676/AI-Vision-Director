# Container definitions

- `Dockerfile.api` builds the API, migration, edge-sync, and integration-test image.
- `Dockerfile.benchmark` builds the CUDA benchmark worker image.
- `dashboard/Dockerfile` builds the web dashboard from its own build context.

Use the repository root as the build context for both Dockerfiles in this directory.
