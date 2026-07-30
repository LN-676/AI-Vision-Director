import type { Metadata } from "next";
import { RemoteConsole } from "./remote-console";

export const metadata: Metadata = {
  title: "Remote Console",
  description: "Tablet-first Edge AI remote control console.",
};

export default function RemotePage() {
  return (
    <RemoteConsole
      apiBaseUrl={process.env.NEXT_PUBLIC_AIVD_API_BASE_URL?.trim() || null}
    />
  );
}
