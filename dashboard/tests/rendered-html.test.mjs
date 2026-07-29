import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${path}`, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the Mission Control shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Mission Control · AI Vision Director<\/title>/i);
  assert.match(html, /Mission Control/);
  assert.match(html, /Overview/);
  assert.match(html, /Vehicles/);
  assert.match(html, /Sessions/);
  assert.match(html, /Events/);
  assert.match(html, /Read-only dashboard/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/i);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/i);
});

test("server-renders the tablet Remote Console route", async () => {
  const response = await render("/remote");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Remote Console · AI Vision Director/);
  assert.match(html, /AI Vision Director Remote Console/);
  assert.match(html, /Connecting to Edge control plane/);
});

test("typed client keeps the read-only API boundary explicit", async () => {
  const client = await readFile(
    new URL("../app/lib/api-client.ts", import.meta.url),
    "utf8",
  );
  assert.match(client, /interface VisionApi/);
  assert.match(client, /\/api\/v3\/system\/status/);
  assert.match(client, /\/api\/v3\/vehicles\?limit=100/);
  assert.match(client, /\/api\/v3\/sessions\?limit=100/);
  assert.match(client, /\/api\/v3\/events\?limit=100/);
  assert.doesNotMatch(client, /method:\s*["'](?:POST|PATCH|PUT|DELETE)/i);
});

test("telemetry socket reconnects with bounded backoff and cleans up", async () => {
  const socket = await readFile(
    new URL("../app/lib/use-telemetry-socket.ts", import.meta.url),
    "utf8",
  );
  assert.match(socket, /MAX_BACKOFF_MS = 30_000/);
  assert.match(socket, /socket\.onclose/);
  assert.match(socket, /setTimeout\(connect, exponential \+ jitter\)/);
  assert.match(socket, /addEventListener\("online"/);
  assert.match(socket, /addEventListener\("offline"/);
  assert.match(socket, /removeEventListener\("online"/);
  assert.match(socket, /socket\?\.close\(\)/);
});

test("dashboard has distinct loading, error, and empty states", async () => {
  const dashboard = await readFile(
    new URL("../app/vision-dashboard.tsx", import.meta.url),
    "utf8",
  );
  assert.match(dashboard, /Loading data/);
  assert.match(dashboard, /Could not load vehicles/);
  assert.match(dashboard, /Registry is empty/);
  assert.match(dashboard, /No sessions recorded/);
  assert.match(dashboard, /No events to display/);
  assert.match(dashboard, /Retry request/);
});

test("remote console uses high-level commands and confirms emergency stop", async () => {
  const remote = await readFile(
    new URL("../app/remote/remote-console.tsx", import.meta.url),
    "utf8",
  );
  const client = await readFile(
    new URL("../app/lib/remote-api-client.ts", import.meta.url),
    "utf8",
  );
  assert.match(remote, /start_tracking/);
  assert.match(remote, /stop_tracking/);
  assert.match(remote, /TAP AGAIN — CONFIRM EMERGENCY STOP/);
  assert.match(remote, /Control API Offline/);
  assert.match(remote, /No Edge Mac heartbeat yet/);
  assert.match(remote, /Before \/ After Monitors/);
  assert.match(remote, /Before detection monitor/);
  assert.match(remote, /After reframed monitor/);
  assert.match(client, /method:\s*"POST"/);
  assert.match(client, /\/api\/v3\/edge\/preview\/\$\{view\}/);
  assert.match(client, /expires_at/);
  assert.doesNotMatch(client, /yaw_velocity|pitch_velocity/);
});

test("remote tablet CSS prevents primary horizontal overflow", async () => {
  const css = await readFile(
    new URL("../app/globals.css", import.meta.url),
    "utf8",
  );
  assert.match(css, /\.remote-shell[\s\S]*overflow-x:\s*hidden/);
  assert.match(css, /@media \(max-width: 900px\)/);
  assert.match(css, /\.remote-grid\s*\{\s*grid-template-columns:\s*1fr/);
});
