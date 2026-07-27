import { type NextRequest, NextResponse } from "next/server";
import { accessTokenFor, apiBaseUrl, clearAuthCookies, setTokenCookies } from "@/lib/auth/server";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const token = await accessTokenFor(request);
  if (!token.accessToken) {
    const response = NextResponse.json({ authenticated: false }, { status: 401 });
    clearAuthCookies(response);
    return response;
  }
  const upstream = await fetch(`${apiBaseUrl()}/api/v1/me`, {
    headers: { Authorization: `Bearer ${token.accessToken}` },
    cache: "no-store",
  });
  if (!upstream.ok) {
    const response = NextResponse.json({ authenticated: false }, { status: 401 });
    clearAuthCookies(response);
    return response;
  }
  const user = (await upstream.json()) as unknown;
  const response = NextResponse.json({ authenticated: true, user });
  if (token.refreshed) setTokenCookies(response, token.refreshed);
  response.headers.set("Cache-Control", "no-store");
  return response;
}
