import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/auth/logout/route";

vi.mock("@/lib/auth/server", () => ({
  appBaseUrl: () => "http://localhost:3000",
  clearAuthCookies: () => undefined,
  ID_COOKIE: "id_token",
  oidcMetadata: async () => ({}),
}));

describe("POST /api/auth/logout", () => {
  it("rejects cross-site form posts with 403", async () => {
    const request = new NextRequest("http://localhost:3000/api/auth/logout", {
      method: "POST",
      headers: {
        origin: "https://evil.example",
        "sec-fetch-site": "cross-site",
      },
    });
    const response = await POST(request);
    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ detail: "Cross-site request rejected" });
  });

  it("allows same-origin posts", async () => {
    const request = new NextRequest("http://localhost:3000/api/auth/logout", {
      method: "POST",
      headers: {
        origin: "http://localhost:3000",
        "sec-fetch-site": "same-origin",
      },
    });
    const response = await POST(request);
    expect(response.status).toBe(303);
  });
});
