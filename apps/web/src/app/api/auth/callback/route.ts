import { type NextRequest, NextResponse } from "next/server";
import {
  apiBaseUrl,
  appBaseUrl,
  clearAuthCookies,
  equalState,
  exchangeCode,
  RETURN_TO_COOKIE,
  STATE_COOKIE,
  safeReturnTo,
  setTokenCookies,
  VERIFIER_COOKIE,
} from "@/lib/auth/server";

function authError(detail: string): NextResponse {
  const target = new URL("/", appBaseUrl());
  target.searchParams.set("auth_error", detail);
  const response = NextResponse.redirect(target, 303);
  clearAuthCookies(response);
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const providerError = request.nextUrl.searchParams.get("error");
  if (providerError) {
    // Never reflect provider error_description — attacker-controlled phishing text.
    return authError("Sign-in was cancelled or denied by the identity provider.");
  }

  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  const expectedState = request.cookies.get(STATE_COOKIE)?.value;
  const verifier = request.cookies.get(VERIFIER_COOKIE)?.value;
  if (!code || !verifier || !equalState(expectedState, state)) {
    return authError("The login response could not be verified. Please try again.");
  }

  try {
    const tokens = await exchangeCode(code, verifier);
    // FastAPI is the authorization source of truth. Accepting the frontend
    // session only after /me succeeds verifies issuer, audience, required claims,
    // tenant identity, user status, and the database mapping end to end.
    const verified = await fetch(`${apiBaseUrl()}/api/v1/me`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
      cache: "no-store",
    });
    if (!verified.ok) {
      return authError("The identity is not authorized for this application.");
    }

    const returnTo = safeReturnTo(request.cookies.get(RETURN_TO_COOKIE)?.value ?? null);
    const response = NextResponse.redirect(new URL(returnTo, appBaseUrl()), 303);
    clearAuthCookies(response);
    setTokenCookies(response, tokens);
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return authError("Login could not be completed. Please try again.");
  }
}
