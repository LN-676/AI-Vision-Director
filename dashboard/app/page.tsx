import type { Metadata } from "next";
import { requireSiteAccess } from "./lib/site-access";
import { VisionDashboard } from "./vision-dashboard";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Mission Control",
  description:
    "Live operational visibility for vehicles, capture sessions, and edge telemetry.",
};

export default async function Home() {
  await requireSiteAccess("/");
  return <VisionDashboard />;
}
