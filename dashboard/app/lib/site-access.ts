import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getChatGPTUser } from "../chatgpt-auth";

export const DEVICE_COOKIE = "aivd_device";

type AccessEnv = {
  AIVD_INVITE_TOKEN_HASH?: string;
  AIVD_OWNER_EMAIL?: string;
  DB?: D1Database;
};

async function accessEnv(): Promise<AccessEnv> {
  const cloudflare = await import("cloudflare:workers");
  return cloudflare.env as unknown as AccessEnv;
}

export async function getAccessDatabase(): Promise<D1Database> {
  const database = (await accessEnv()).DB;
  if (!database) throw new Error("Device access database is unavailable.");
  return database;
}

export async function getInviteTokenHash(): Promise<string> {
  return (await accessEnv()).AIVD_INVITE_TOKEN_HASH?.trim() ?? "";
}

export async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function randomSecret(byteLength = 32): string {
  const bytes = crypto.getRandomValues(new Uint8Array(byteLength));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

export async function isSiteViewerAuthorized(): Promise<boolean> {
  const user = await getChatGPTUser();
  const ownerEmail = (
    process.env.AIVD_OWNER_EMAIL ??
    (await accessEnv()).AIVD_OWNER_EMAIL
  )
    ?.trim()
    .toLowerCase();
  if (ownerEmail && user?.email.toLowerCase() === ownerEmail) return true;

  const inviteHash = await getInviteTokenHash();
  const deviceSecret = (await cookies()).get(DEVICE_COOKIE)?.value;
  if (!inviteHash || !deviceSecret) return false;

  try {
    const deviceHash = await sha256(deviceSecret);
    const row = await (await getAccessDatabase())
      .prepare(
        "SELECT invite_hash FROM device_claims WHERE invite_hash = ? AND device_hash = ? LIMIT 1",
      )
      .bind(inviteHash, deviceHash)
      .first();
    return Boolean(row);
  } catch {
    return false;
  }
}

export async function requireSiteAccess(returnTo: string): Promise<void> {
  if (await isSiteViewerAuthorized()) return;
  redirect(`/access?return_to=${encodeURIComponent(returnTo)}`);
}
