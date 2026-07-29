# React Dashboard — V3 Phase 4

Phase 4 adds a browser operations surface without weakening the API boundaries
established in Phases 0–3.

## Runtime boundary

- The dashboard is located in `dashboard/` and uses React with vinext.
- `VisionApi` is a typed client for system status, vehicles, sessions, and
  events. Phase 4 sends GET requests only.
- When `NEXT_PUBLIC_AIVD_API_BASE_URL` is absent, deterministic demo data keeps
  previews and deployments usable without exposing a private edge node.
- `NEXT_PUBLIC_AIVD_WS_URL` enables live telemetry. The socket reconnects with
  exponential backoff, a 30-second cap, jitter, online/offline awareness, and
  full timer/listener cleanup.
- Public browser configuration contains origins only. Credentials and Firebase
  private keys are never placed in `NEXT_PUBLIC_*` variables.

## UX states

Overview, vehicles, sessions, and events each distinguish loading, error, empty,
and ready states. Error panels expose a retry action; filtered searches and event
severity filters have their own empty results. Mobile layout collapses the
sidebar into horizontal navigation.

## Deployment

The dashboard is packaged independently by Sites. `.openai/hosting.json` stores
the opaque Sites project identifier after site creation. Production API and
WebSocket origins should be configured in the deployment environment and must
use HTTPS/WSS with the Phase 3 CORS allowlist.
