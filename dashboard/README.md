# AI Vision Director Mission Control

React/vinext read-only operations dashboard for AI-Vision-Director V3.0.0b1.

## Local development

Requires Node.js 22.13 or newer.

```bash
npm install
npm run dev
```

Without environment variables the dashboard starts in deterministic demo mode.
To connect a deployment to the V3 API, copy `.env.example` to `.env.local` and
set:

- `NEXT_PUBLIC_AIVD_API_BASE_URL` — HTTPS origin for the read-only V3 API.
- `NEXT_PUBLIC_AIVD_WS_URL` — WSS telemetry endpoint.

Both values are public browser configuration and must never contain credentials.
Firebase tokens are supplied at runtime by an auth provider when write features
are added; this Phase 4 dashboard issues GET requests only.

## Verification

```bash
npm run lint
npm test
```

The tests verify server rendering, typed read-only API paths, dashboard
loading/error/empty states, and bounded WebSocket reconnect behavior.
