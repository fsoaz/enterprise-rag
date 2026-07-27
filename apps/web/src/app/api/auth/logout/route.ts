import { type NextRequest, NextResponse } from "next/server";
import { appBaseUrl, clearAuthCookies, ID_COOKIE, oidcMetadata } from "@/lib/auth/server";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const metadata = await oidcMetadata();
  const logout = metadata.end_session_endpoint
    ? new URL(metadata.end_session_endpoint)
    : new URL("/", appBaseUrl());
  if (metadata.end_session_endpoint) {
    logout.searchParams.set("post_logout_redirect_uri", appBaseUrl());
    logout.searchParams.set("client_id", process.env.OIDC_CLIENT_ID ?? "enterprise-rag-web");
    const idToken = request.cookies.get(ID_COOKIE)?.value;
    if (idToken) logout.searchParams.set("id_token_hint", idToken);
  }
  const response = NextResponse.redirect(logout, 303);
  clearAuthCookies(response);
  response.headers.set("Cache-Control", "no-store");
  return response;
}
