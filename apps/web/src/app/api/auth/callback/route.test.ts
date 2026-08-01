import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  clearAuthCookies: vi.fn(),
  setTokenCookies: vi.fn(),
  equalState: vi.fn(),
  exchangeCode: vi.fn(),
  safeReturnTo: vi.fn((value: string | null) => {
    if (!value?.startsWith("/") || value.startsWith("//")) return "/";
    return value;
  }),
}));

vi.mock("@/lib/auth/server", () => ({
  apiBaseUrl: () => "http://api.test",
  appBaseUrl: () => "http://localhost:3000",
  clearAuthCookies: auth.clearAuthCookies,
  equalState: auth.equalState,
  exchangeCode: auth.exchangeCode,
  RETURN_TO_COOKIE: "return_to",
  safeReturnTo: auth.safeReturnTo,
  setTokenCookies: auth.setTokenCookies,
  STATE_COOKIE: "oidc_state",
  VERIFIER_COOKIE: "oidc_verifier",
}));

import { GET } from "@/app/api/auth/callback/route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("GET /api/auth/callback", () => {
  it("maps provider errors to provider_denied without reflecting descriptions", async () => {
    const request = new NextRequest(
      "http://localhost:3000/api/auth/callback?error=access_denied&error_description=Call%20555",
    );
    const response = await GET(request);
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/?auth_error=provider_denied",
    );
  });

  it("maps state mismatch to a fixed code", async () => {
    auth.equalState.mockReturnValue(false);
    const request = new NextRequest(
      "http://localhost:3000/api/auth/callback?code=abc&state=wrong",
      {
        headers: { cookie: "oidc_state=expected; oidc_verifier=verifier" },
      },
    );
    const response = await GET(request);
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/?auth_error=state_mismatch",
    );
  });

  it("uses safeReturnTo so //evil.com cannot open-redirect", async () => {
    auth.equalState.mockReturnValue(true);
    auth.exchangeCode.mockResolvedValue({
      access_token: "access",
      expires_in: 3600,
    });
    auth.safeReturnTo.mockReturnValue("/");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "user" }), { status: 200 })),
    );

    const request = new NextRequest("http://localhost:3000/api/auth/callback?code=abc&state=good", {
      headers: { cookie: "oidc_state=good; oidc_verifier=verifier; return_to=//evil.com" },
    });
    const response = await GET(request);
    expect(response.status).toBe(303);
    expect(auth.safeReturnTo).toHaveBeenCalledWith("//evil.com");
    expect(response.headers.get("location")).toBe("http://localhost:3000/");
    expect(auth.setTokenCookies).toHaveBeenCalled();
  });
});
