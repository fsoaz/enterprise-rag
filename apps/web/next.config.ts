import type { NextConfig } from "next";

// Security headers (including nonce CSP) are set in src/middleware.ts so the
// script-src nonce can be generated per request. Do not re-add a static CSP here.
const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
