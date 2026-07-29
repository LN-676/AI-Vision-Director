import { NextResponse } from "next/server";
import {
  DEVICE_COOKIE,
  getAccessDatabase,
  getInviteTokenHash,
  randomSecret,
  sha256,
} from "../../lib/site-access";

const NO_STORE_HEADERS = {
  "Cache-Control": "no-store, max-age=0",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
};

function htmlPage(title: string, message: string, form = ""): Response {
  return new Response(
    `<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>${escapeHtml(title)} · AI Vision Director</title>
    <style>
      :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #070b12; color: #f3f6fb; }
      main { width: min(88vw, 30rem); padding: 2rem; border: 1px solid #27354a; border-radius: 1.25rem; background: #101722; box-shadow: 0 1.5rem 5rem #0008; }
      small { color: #70e1b2; letter-spacing: .14em; font-weight: 700; }
      h1 { margin: .65rem 0 .75rem; font-size: clamp(1.8rem, 8vw, 2.7rem); }
      p { color: #aeb9c9; line-height: 1.6; }
      button { width: 100%; margin-top: 1rem; padding: .95rem 1rem; border: 0; border-radius: .8rem; background: #70e1b2; color: #07100c; font: inherit; font-weight: 800; cursor: pointer; }
    </style>
  </head>
  <body><main><small>AI VISION DIRECTOR</small><h1>${escapeHtml(title)}</h1><p>${escapeHtml(message)}</p>${form}</main></body>
</html>`,
    {
      status: title === "Invalid invitation" ? 403 : 200,
      headers: { "Content-Type": "text/html; charset=utf-8", ...NO_STORE_HEADERS },
    },
  );
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

async function invitationIsValid(token: string): Promise<boolean> {
  const expectedHash = await getInviteTokenHash();
  return Boolean(expectedHash) && (await sha256(token)) === expectedHash;
}

async function invitationIsClaimed(inviteHash: string): Promise<boolean> {
  const row = await (await getAccessDatabase())
    .prepare(
      "SELECT invite_hash FROM device_claims WHERE invite_hash = ? LIMIT 1",
    )
    .bind(inviteHash)
    .first();
  return Boolean(row);
}

export async function GET(request: Request) {
  const token = new URL(request.url).searchParams.get("token")?.trim() ?? "";
  if (!token || !(await invitationIsValid(token))) {
    return htmlPage("Invalid invitation", "This invitation link is not valid.");
  }

  const inviteHash = await getInviteTokenHash();
  if (await invitationIsClaimed(inviteHash)) {
    return NextResponse.redirect(new URL("/access?reason=claimed", request.url));
  }

  const form = `<form method="post">
    <input type="hidden" name="token" value="${escapeHtml(token)}">
    <button type="submit">Authorize this mobile browser</button>
  </form>`;
  return htmlPage(
    "Authorize this device",
    "Only the first mobile browser that confirms this invitation will receive access.",
    form,
  );
}

export async function POST(request: Request) {
  const form = await request.formData();
  const token = String(form.get("token") ?? "").trim();
  if (!token || !(await invitationIsValid(token))) {
    return htmlPage("Invalid invitation", "This invitation link is not valid.");
  }

  const inviteHash = await getInviteTokenHash();
  const deviceSecret = randomSecret();
  const deviceHash = await sha256(deviceSecret);
  const database = await getAccessDatabase();

  await database
    .prepare(
      "INSERT OR IGNORE INTO device_claims (invite_hash, device_hash, claimed_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
    )
    .bind(inviteHash, deviceHash)
    .run();

  const claim = await database
    .prepare(
      "SELECT device_hash FROM device_claims WHERE invite_hash = ? LIMIT 1",
    )
    .bind(inviteHash)
    .first<{ device_hash: string }>();

  if (claim?.device_hash !== deviceHash) {
    return NextResponse.redirect(new URL("/access?reason=claimed", request.url));
  }

  const response = NextResponse.redirect(new URL("/", request.url), 303);
  response.headers.set("Cache-Control", "no-store, max-age=0");
  response.cookies.set(DEVICE_COOKIE, deviceSecret, {
    httpOnly: true,
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
    sameSite: "strict",
    secure: true,
  });
  return response;
}
