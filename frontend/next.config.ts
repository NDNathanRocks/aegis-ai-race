import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // The browser talks to the FastAPI backend directly (NEXT_PUBLIC_API_URL): a Next rewrite proxy would buffer SSE.
};

export default nextConfig;
