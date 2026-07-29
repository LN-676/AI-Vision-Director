import type { Metadata } from "next";
import { requireSiteAccess } from "../lib/site-access";
import { RemoteConsole } from "./remote-console";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Remote Console",
  description: "Tablet-first Edge AI remote control console.",
};

export default async function RemotePage() {
  await requireSiteAccess("/remote");
  return <RemoteConsole />;
}
