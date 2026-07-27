import { describe, expect, it } from "vitest";
import { SseParser } from "@/lib/sse";

describe("SseParser", () => {
  it("parses frames split across chunks and resets the event name", () => {
    const parser = new SseParser();

    expect(parser.push('event: token\ndata: {"te')).toEqual([]);
    expect(parser.push('xt":"hello"}\n\n')).toEqual([{ event: "token", data: { text: "hello" } }]);
    expect(parser.push('data: {"stage":"done"}\n\n')).toEqual([
      { event: "message", data: { stage: "done" } },
    ]);
  });

  it("drops only a malformed frame and continues parsing", () => {
    const parser = new SseParser();
    expect(parser.push("event: token\ndata: not-json\n\n")).toEqual([]);
    expect(parser.push('event: done\ndata: {"query_id":"q-1"}\n\n')).toEqual([
      { event: "done", data: { query_id: "q-1" } },
    ]);
  });
});
