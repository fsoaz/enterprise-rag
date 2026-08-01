import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  accessTokenFor: vi.fn(),
  clearAuthCookies: vi.fn(),
  refreshTokens: vi.fn(),
  setTokenCookies: vi.fn(),
  tokenCookies: vi.fn(),
}));

vi.mock("@/lib/auth/server", () => ({
  accessTokenFor: auth.accessTokenFor,
  apiBaseUrl: () => "http://api.test",
  clearAuthCookies: auth.clearAuthCookies,
  refreshTokens: auth.refreshTokens,
  setTokenCookies: auth.setTokenCookies,
  tokenCookies: auth.tokenCookies,
}));

import { GET, POST } from "@/app/api/backend/[...path]/route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function backendRequest(
  method: string,
  path = "http://localhost:3000/api/backend/api/v1/me",
  headers: Record<string, string> = {},
): NextRequest {
  return new NextRequest(path, {
    method,
    headers: {
      origin: "http://localhost:3000",
      "sec-fetch-site": "same-origin",
      ...headers,
    },
  });
}

describe("BFF /api/backend proxy", () => {
  it("rejects cross-site mutations with 403", async () => {
    const request = new NextRequest("http://localhost:3000/api/backend/api/v1/me", {
      method: "POST",
      headers: {
        origin: "https://evil.example",
        "sec-fetch-site": "cross-site",
      },
    });
    const response = await POST(request, {
      params: Promise.resolve({ path: ["api", "v1", "me"] }),
    });
    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ detail: "Cross-site request rejected" });
  });

  it("clears cookies and returns 401 when no access token is available", async () => {
    auth.accessTokenFor.mockResolvedValue({ accessToken: null });
    const response = await GET(backendRequest("GET"), {
      params: Promise.resolve({ path: ["api", "v1", "me"] }),
    });
    expect(response.status).toBe(401);
    expect(auth.clearAuthCookies).toHaveBeenCalled();
    await expect(response.json()).resolves.toEqual({ detail: "Authentication required" });
  });

  it("retries once after refreshing when the upstream returns 401", async () => {
    auth.accessTokenFor.mockResolvedValue({ accessToken: "stale-token" });
    auth.tokenCookies.mockReturnValue({ refreshToken: "refresh-me", expiresAt: 0 });
    auth.refreshTokens.mockResolvedValue({
      access_token: "fresh-token",
      expires_in: 3600,
    });

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "expired" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(backendRequest("GET"), {
      params: Promise.resolve({ path: ["api", "v1", "me"] }),
    });

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(auth.refreshTokens).toHaveBeenCalledWith("refresh-me");
    expect(auth.setTokenCookies).toHaveBeenCalled();
    const secondInit = fetchMock.mock.calls[1]?.[1] as RequestInit | undefined;
    expect(secondInit).toBeDefined();
    const secondCallHeaders = secondInit?.headers as Headers;
    expect(secondCallHeaders.get("Authorization")).toBe("Bearer fresh-token");
  });
});
