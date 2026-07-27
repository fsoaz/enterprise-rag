import { type NextRequest, NextResponse } from "next/server";
import {
  appBaseUrl,
  callbackUrl,
  oidcMetadata,
  pkceChallenge,
  RETURN_TO_COOKIE,
  randomUrlSafe,
  STATE_COOKIE,
  safeReturnTo,
  setTransientCookie,
  VERIFIER_COOKIE,
} from "@/lib/auth/server";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const metadata = await oidcMetadata();
  const state = randomUrlSafe();
  const verifier = randomUrlSafe(64);
  const authorization = new URL(metadata.authorization_endpoint);
  authorization.searchParams.set("client_id", process.env.OIDC_CLIENT_ID ?? "enterprise-rag-web");
  authorization.searchParams.set("response_type", "code");
  authorization.searchParams.set("redirect_uri", callbackUrl());
  // Standard authorization-code sessions already receive a refresh token.
  // `offline_access` is intentionally not requested: that scope creates a
  // long-lived offline session and requires a separate Keycloak role/consent.
  authorization.searchParams.set("scope", "openid profile email");
  authorization.searchParams.set("state", state);
  authorization.searchParams.set("code_challenge", pkceChallenge(verifier));
  authorization.searchParams.set("code_challenge_method", "S256");

  const response = NextResponse.redirect(authorization);
  setTransientCookie(response, STATE_COOKIE, state);
  setTransientCookie(response, VERIFIER_COOKIE, verifier);
  setTransientCookie(
    response,
    RETURN_TO_COOKIE,
    safeReturnTo(request.nextUrl.searchParams.get("returnTo")),
  );
  response.headers.set("Cache-Control", "no-store");
  response.headers.set(
    "Content-Security-Policy",
    `default-src 'none'; form-action ${appBaseUrl()}`,
  );
  return response;
}
