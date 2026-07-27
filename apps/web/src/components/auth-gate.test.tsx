import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AuthGate } from "@/components/auth-gate";
import { renderWithLocale } from "@/test/render";

describe("AuthGate", () => {
  it("shows a sign-in action when no session exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));

    renderWithLocale(
      <AuthGate>
        <div>private content</div>
      </AuthGate>,
    );

    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/api/auth/login",
    );
    expect(screen.queryByText("private content")).not.toBeInTheDocument();
  });

  it("renders the authenticated user and logout control", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          authenticated: true,
          user: {
            email: "member@acme.example",
            external_subject: "acme-member",
            roles: ["member"],
          },
        }),
      ),
    );

    renderWithLocale(
      <AuthGate>
        <div>private content</div>
      </AuthGate>,
    );

    expect(await screen.findByText("member@acme.example")).toBeInTheDocument();
    expect(screen.getByText("private content")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" }).closest("form")).toHaveAttribute(
      "action",
      "/api/auth/logout",
    );
  });
});
