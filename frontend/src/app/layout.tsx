import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DualSight: Naive AI vs. Nathan's Engineered AI",
  description:
    "A live split-screen race between a naive LLM wrapper and an engineered AI platform: DualSight hybrid retrieval, semantic cache, model routing, critic agent and schema enforcement.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#090A0F",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
