import type { NextRequest } from "next/server";

/** Same-origin gate for cookie-mutating requests (logout, BFF proxy writes). */
export function sameOriginMutation(request: NextRequest): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return true;
  const origin = request.headers.get("origin");
  const fetchSite = request.headers.get("sec-fetch-site");
  return (!origin || origin === request.nextUrl.origin) && fetchSite !== "cross-site";
}
