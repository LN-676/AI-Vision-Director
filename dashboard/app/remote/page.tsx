import type { Metadata } from "next";
import { RemoteConsole } from "./remote-console";

export const metadata: Metadata = {
  title: "Remote Console",
  description: "Tablet-first Edge AI remote control console.",
};

export default function RemotePage() {
  return <RemoteConsole />;
}
