import type { Metadata } from "next";
import { VisionDashboard } from "./vision-dashboard";

export const metadata: Metadata = {
  title: "Mission Control",
  description:
    "Live operational visibility for vehicles, capture sessions, and edge telemetry.",
};

export default function Home() {
  return <VisionDashboard />;
}
