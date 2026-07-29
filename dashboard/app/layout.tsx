import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "AI Vision Director",
    template: "%s · AI Vision Director",
  },
  description:
    "Live operational visibility for an AI-powered vehicle filming system.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
  openGraph: {
    title: "AI Vision Director · Mission Control",
    description:
      "Live operational visibility for vehicles, capture sessions, and edge telemetry.",
    images: [
      {
        url: "/og.png",
        width: 1731,
        height: 909,
        alt: "AI Vision Director vehicle telemetry visualization",
      },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
