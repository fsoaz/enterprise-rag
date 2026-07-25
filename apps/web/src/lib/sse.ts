/**
 * Server-sent events parser.
 *
 * Written to the frame rules rather than line-by-line: an event ends at a blank
 * line, `event:` resets to "message" for each new frame, and multiple `data:`
 * lines join with newlines. The previous inline version carried `event` across
 * frame boundaries, so any frame without an explicit `event:` was attributed to
 * whatever came before it.
 */
export type SseEvent = { event: string; data: unknown };

export class SseParser {
  private buffer = "";
  private dataLines: string[] = [];
  private eventName = "message";

  /** Feed a decoded chunk; returns whatever complete events it completed. */
  push(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const events: SseEvent[] = [];
    let newlineIndex = this.buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      // Tolerate CRLF as well as LF.
      const line = this.buffer.slice(0, newlineIndex).replace(/\r$/, "");
      this.buffer = this.buffer.slice(newlineIndex + 1);
      const completed = this.consumeLine(line);
      if (completed) events.push(completed);
      newlineIndex = this.buffer.indexOf("\n");
    }
    return events;
  }

  private consumeLine(line: string): SseEvent | null {
    if (line === "") return this.flush();
    if (line.startsWith(":")) return null; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") this.eventName = value;
    else if (field === "data") this.dataLines.push(value);
    return null;
  }

  /** Emit any frame left unterminated when the stream ends. */
  flush(): SseEvent | null {
    if (this.dataLines.length === 0) {
      this.eventName = "message";
      return null;
    }
    const raw = this.dataLines.join("\n");
    const event = this.eventName;
    this.dataLines = [];
    this.eventName = "message";
    try {
      return { event, data: JSON.parse(raw) };
    } catch {
      // A malformed frame must not abort the stream and discard everything
      // already rendered — drop just this frame.
      return null;
    }
  }
}
