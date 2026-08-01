/**
 * Shared API client.
 *
 * The base URL is read once, here. Both pages previously inlined
 * `process.env.NEXT_PUBLIC_API_BASE`, while compose supplied
 * `NEXT_PUBLIC_API_BASE_URL` — a name mismatch that silently fell through to the
 * hardcoded localhost default in every deployment. `NEXT_PUBLIC_*` is also
 * inlined at build time, so it has to arrive as a Docker build arg rather than a
 * runtime environment entry.
 */
/** Dev-only impersonation. Gated so the control cannot ship in a real build. */
export const DEV_AUTH = (process.env.NEXT_PUBLIC_DEV_AUTH ?? "false").toLowerCase() === "true";

/**
 * Production requests stay same-origin and are authenticated by the web BFF.
 * Only the explicitly enabled development mode calls FastAPI from the browser.
 */
export const API_BASE = DEV_AUTH
  ? (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000")
  : "/api/backend";

export type Citation = {
  chunkId: string;
  documentVersionId: string;
  documentTitle: string;
  citedText: string;
  startChar: number;
  endChar: number;
  /** Index of the answer sentence this citation supports. */
  answerSentenceIdx: number;
  staleness: string;
  /** Passage matched prompt-injection heuristics at ingest. */
  isSuspect: boolean;
};

export type Verdict = "grounded" | "partial" | "unsupported";

export type ChatMessage = components["schemas"]["ChatMessage"];
export type ChatRequest = components["schemas"]["ChatRequest"];

export function authHeaders(user: string): Record<string, string> {
  return DEV_AUTH ? { "X-Dev-User": user } : {};
}

/** RFC 7807 problem+json, which every API error uses. */
export async function problemDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string; title?: string };
    return body.detail ?? body.title ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

import type { components } from "@/lib/generated/api";
