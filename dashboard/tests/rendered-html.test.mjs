import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
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
