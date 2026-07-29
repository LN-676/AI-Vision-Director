import type { Metadata } from "next";
import { chatGPTSignInPath } from "../chatgpt-auth";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Restricted access",
  description: "This AI Vision Director site requires an authorized device.",
};

type AccessPageProps = {
  searchParams: Promise<{ reason?: string; return_to?: string }>;
};

function safeReturnTo(value: string | undefined): string {
  if (!value?.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}

export default async function AccessPage({ searchParams }: AccessPageProps) {
  const params = await searchParams;
  const claimed = params.reason === "claimed";
  const returnTo = safeReturnTo(params.return_to);

  return (
    <main className="access-shell">
      <section className="access-card">
        <p className="access-kicker">AI VISION DIRECTOR</p>
        <h1>{claimed ? "Invitation already used" : "Restricted access"}</h1>
        <p>
          {claimed
            ? "This one-time invitation is already bound to another mobile browser."
            : "Open the one-time invitation link on the mobile browser that should be authorized."}
        </p>
        <a className="access-owner-link" href={chatGPTSignInPath(returnTo)}>
          Owner sign in
        </a>
      </section>
    </main>
  );
}
