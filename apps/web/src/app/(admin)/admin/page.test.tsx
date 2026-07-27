import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AdminPage from "@/app/(admin)/admin/page";
import { renderWithLocale } from "@/test/render";

const document = {
  id: "document-1",
  collection_id: "collection-1",
  title: "Security handbook",
  language: "en",
  archived_at: null,
  created_at: "2026-07-01T12:00:00Z",
  current_version_id: "version-1",
};

describe("AdminPage documents", () => {
  it("lists documents, exposes ingestion history, and archives without reloading", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v1/collections")) {
        return Response.json({ data: [{ id: "collection-1", name: "Policies" }] });
      }
      if (url.endsWith("/api/v1/documents?limit=100")) {
        return Response.json({ data: [document] });
      }
      if (url.endsWith("/api/v1/documents/document-1/jobs")) {
        return Response.json({
          data: [
            {
              id: "job-1",
              stage: "index",
              status: "failed",
              error: "Vector service unavailable",
              attempts: 2,
              created_at: "2026-07-01T12:01:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/api/v1/documents/document-1/archive") && init?.method === "POST") {
        return Response.json({ ...document, archived_at: "2026-07-27T12:00:00Z" });
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithLocale(<AdminPage />);

    expect(await screen.findByRole("heading", { name: "Security handbook" })).toBeVisible();
    expect(screen.getAllByText("Policies", { exact: false })).toHaveLength(2);
    expect(screen.getByText("Active")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "View jobs" }));
    expect(await screen.findByText("Vector service unavailable")).toBeVisible();
    expect(screen.getByText("index", { exact: false })).toBeVisible();
    expect(screen.getByText("2 attempts", { exact: false })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(await screen.findByText("Archived")).toBeVisible();
    expect(screen.getByRole("button", { name: "Restore" })).toBeEnabled();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/backend/api/v1/documents/document-1/archive",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
