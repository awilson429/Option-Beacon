import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Browser /api/* is handled by app/api/[...path]/route.ts so SSE streams
  // through a Node proxy instead of next.config rewrites, which can buffer.
};

export default nextConfig;
