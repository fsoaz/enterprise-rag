import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ChatPage from "@/app/(chat)/page";
import { renderWithLocale } from "@/test/render";

function sseResponse(frames: Array<[string, Record<string, unknown>]>): Response {
  const encoder = new TextEncoder();
  const body = frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  return new Response(
    new ReadableStream({
      start(controller) {
        // Split inside a frame too; the component must not rely on network chunks
        // lining up with SSE event boundaries.
        const encoded = encoder.encode(body.join(""));
        const midpoint = Math.floor(encoded.length / 2);
        controller.enqueue(encoded.slice(0, midpoint));
        controller.enqueue(encoded.slice(midpoint));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

describe("ChatPage citations", () => {
  it("shows the groundedness verification stage before releasing an answer", async () => {
    const encoder = new TextEncoder();
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
    const response = new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller;
          controller.enqueue(encoder.encode('event: status\ndata: {"stage":"verifying"}\n\n'));
        },
      }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const user = userEvent.setup();
    renderWithLocale(<ChatPage />);

    await user.type(screen.getByLabelText("Your question"), "What supports this answer?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Checking support and citations…")).toBeVisible();

    streamController?.enqueue(
      encoder.encode(
        'event: token\ndata: {"text":"Verified answer."}\n\nevent: done\ndata: {"query_id":"query-progress"}\n\n',
      ),
    );
    streamController?.close();
    expect(await screen.findByText("Verified answer.")).toBeVisible();
  });

  it("renders unique sequential anchors and drops invalid sentence bindings", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          ["token", { text: "First claim. Second claim." }],
          [
            "citation",
            {
              chunk_id: "chunk-a",
              document_version_id: "version-a",
              document_title: "Policy A",
              cited_text: "Evidence A",
              start_char: 0,
              end_char: 10,
              answer_sentence_idx: 0,
              staleness: "fresh",
            },
          ],
          [
            "citation",
            {
              chunk_id: "chunk-b",
              document_version_id: "version-b",
              document_title: "Policy B",
              cited_text: "Evidence B",
              start_char: 11,
              end_char: 20,
              answer_sentence_idx: 0,
              staleness: "fresh",
            },
          ],
          [
            "citation",
            {
              chunk_id: "chunk-invalid",
              document_version_id: "version-invalid",
              document_title: "Invalid source",
              cited_text: "No rendered sentence has this index",
              start_char: 0,
              end_char: 5,
              answer_sentence_idx: 99,
              staleness: "unknown",
            },
          ],
          ["verdict", { groundedness: "grounded" }],
          ["done", { query_id: "query-1" }],
        ]),
      ),
    );
    const user = userEvent.setup();
    renderWithLocale(<ChatPage />);

    await user.type(screen.getByLabelText("Your question"), "What does the policy say?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    const firstLink = await screen.findByRole("link", { name: "Jump to source 1" });
    const secondLink = screen.getByRole("link", { name: "Jump to source 2" });
    expect(firstLink).toHaveAttribute("href", "#citation-1");
    expect(secondLink).toHaveAttribute("href", "#citation-2");
    expect(document.querySelectorAll("#citation-1")).toHaveLength(1);
    expect(document.querySelectorAll("#citation-2")).toHaveLength(1);
    expect(screen.queryByText("Invalid source")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled());
  });

  it("sends bounded conversation messages on a follow-up turn", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        sseResponse([
          ["token", { text: "The policy allows two days." }],
          ["done", { query_id: "query-1" }],
        ]),
      )
      .mockResolvedValueOnce(
        sseResponse([
          ["token", { text: "Contractors need approval." }],
          ["done", { query_id: "query-2" }],
        ]),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithLocale(<ChatPage />);

    const question = screen.getByLabelText("Your question");
    await user.type(question, "How many remote days?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("The policy allows two days.")).toBeVisible();

    await user.clear(question);
    await user.type(question, "What about contractors?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Contractors need approval.")).toBeVisible();
    expect(screen.getByText("How many remote days?", { exact: false })).toBeVisible();

    const secondRequest = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect(JSON.parse(String(secondRequest.body))).toEqual({
      messages: [
        { role: "user", content: "How many remote days?" },
        { role: "assistant", content: "The policy allows two days." },
        { role: "user", content: "What about contractors?" },
      ],
      stream: true,
      strategy: "hybrid_rrf",
    });
  });
});
