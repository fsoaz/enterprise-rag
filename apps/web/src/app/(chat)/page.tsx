"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE,
  authHeaders,
  type Citation,
  DEV_AUTH,
  problemDetail,
  type Verdict,
} from "@/lib/api";
import { SseParser } from "@/lib/sse";

type CitationEvent = {
  chunk_id?: string;
  document_version_id?: string;
  document_title?: string;
  cited_text?: string;
  start_char?: number;
  end_char?: number;
  answer_sentence_idx?: number;
  staleness?: string;
};

/** Split an answer into sentences, keeping each sentence's index. */
function splitSentences(text: string): string[] {
  const parts = text.split(/(?<=[.!?])\s+/);
  return parts.filter((part) => part.trim().length > 0);
}

const STALENESS_LABEL: Record<string, string> = {
  fresh: "Current",
  stale: "Past review date",
  superseded: "Superseded by a newer version",
  unknown: "Currency unknown",
};

const STALENESS_TONE: Record<string, string> = {
  fresh: "border-emerald-500/40 text-emerald-700 dark:text-emerald-300",
  stale: "border-amber-500/50 text-amber-700 dark:text-amber-300",
  superseded: "border-rose-500/50 text-rose-700 dark:text-rose-300",
  unknown: "border-neutral-400/40 text-neutral-600 dark:text-neutral-400",
};

export default function ChatPage() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [queryId, setQueryId] = useState<string | null>(null);
  const [user, setUser] = useState("acme-member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedbackState, setFeedbackState] = useState<string | null>(null);
  const [answerLang, setAnswerLang] = useState("en");

  const abortRef = useRef<AbortController | null>(null);

  // Abort any in-flight stream when the component goes away, so the reader loop
  // does not keep running (and setting state) after unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const sentences = useMemo(() => splitSentences(answer), [answer]);

  /** Citations grouped by the answer sentence they support. */
  const citationsBySentence = useMemo(() => {
    const map = new Map<number, Citation[]>();
    for (const citation of citations) {
      const list = map.get(citation.answerSentenceIdx) ?? [];
      list.push(citation);
      map.set(citation.answerSentenceIdx, list);
    }
    return map;
  }, [citations]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setStatus(null);
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setBusy(true);
    setAnswer("");
    setCitations([]);
    setVerdict(null);
    setQueryId(null);
    setError(null);
    setFeedbackState(null);
    setStatus("retrieving");
    // Portuguese answers must not be announced with English phonetics.
    setAnswerLang(/[ãáàâçéêíóôõú]/i.test(question) ? "pt" : "en");

    try {
      const response = await fetch(`${API_BASE}/api/v1/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user) },
        body: JSON.stringify({ question, stream: true }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        setError(await problemDetail(response));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SseParser();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const evt of parser.push(decoder.decode(value, { stream: true }))) {
          handleEvent(evt.event, evt.data);
        }
      }
      const tail = parser.flush();
      if (tail) handleEvent(tail.event, tail.data);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(`Request failed: ${String(err)}`);
      }
    } finally {
      setBusy(false);
      setStatus(null);
      abortRef.current = null;
    }
  }

  function handleEvent(name: string, data: unknown) {
    const payload = (data ?? {}) as Record<string, unknown>;
    if (name === "token") {
      setAnswer((prev) => prev + String(payload.text ?? ""));
    } else if (name === "citation") {
      const c = payload as CitationEvent;
      setCitations((prev) => [
        ...prev,
        {
          chunkId: String(c.chunk_id ?? ""),
          documentVersionId: String(c.document_version_id ?? ""),
          documentTitle: String(c.document_title ?? "Source"),
          citedText: String(c.cited_text ?? ""),
          startChar: Number(c.start_char ?? 0),
          endChar: Number(c.end_char ?? 0),
          answerSentenceIdx: Number(c.answer_sentence_idx ?? 0),
          staleness: String(c.staleness ?? "unknown"),
        },
      ]);
    } else if (name === "status") {
      setStatus(String(payload.stage ?? ""));
    } else if (name === "verdict") {
      setVerdict(String(payload.groundedness ?? "") as Verdict);
    } else if (name === "done") {
      setQueryId(String(payload.query_id ?? ""));
      setStatus(null);
    }
  }

  async function sendFeedback(rating: "up" | "down") {
    if (!queryId || feedbackState === "sending") return;
    setFeedbackState("sending");
    try {
      const response = await fetch(`${API_BASE}/api/v1/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user) },
        body: JSON.stringify({ query_id: queryId, rating }),
      });
      // Silent failure left users believing feedback was recorded when it was not.
      setFeedbackState(response.ok ? "Thanks — feedback recorded." : await problemDetail(response));
    } catch (err) {
      setFeedbackState(`Could not send feedback: ${String(err)}`);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Enterprise RAG</h1>
        <p className="text-neutral-600 dark:text-neutral-400">
          Ask a question grounded in your documents.
        </p>
        {DEV_AUTH ? (
          <label className="text-sm text-neutral-500 dark:text-neutral-400" htmlFor="dev-user">
            Dev user{" "}
            <select
              id="dev-user"
              className="ml-2 rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
              value={user}
              onChange={(e) => setUser(e.target.value)}
            >
              <option value="acme-member">acme-member</option>
              <option value="acme-steward">acme-steward</option>
              <option value="acme-viewer">acme-viewer</option>
              <option value="acme-admin">acme-admin</option>
            </select>
          </label>
        ) : null}
      </header>

      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label htmlFor="question" className="text-sm font-medium">
          Your question
        </label>
        <textarea
          id="question"
          className="min-h-24 w-full rounded border border-neutral-300 bg-transparent p-3 dark:border-neutral-700"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask in Portuguese or English…"
        />
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy || !question.trim()}
            className="self-start rounded bg-neutral-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
          >
            {busy ? "Thinking…" : "Ask"}
          </button>
          {busy ? (
            <button
              type="button"
              onClick={stop}
              className="self-start rounded border border-neutral-300 px-4 py-2 dark:border-neutral-700"
            >
              Stop
            </button>
          ) : null}
        </div>
      </form>

      {/* Streaming output is announced rather than silently appearing. */}
      <p aria-live="polite" className="sr-only">
        {status ? `Status: ${status}` : ""}
      </p>
      {status ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">Status: {status}</p>
      ) : null}

      {error ? (
        <div
          role="alert"
          className="rounded border border-rose-400/60 bg-rose-50 p-3 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200"
        >
          {error}
        </div>
      ) : null}

      {verdict === "unsupported" ? (
        <div
          role="status"
          className="rounded border border-amber-400/60 bg-amber-50 p-3 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
        >
          The system abstained — the corpus does not support a grounded answer.
        </div>
      ) : null}
      {verdict === "partial" ? (
        <div
          role="status"
          className="rounded border border-sky-400/60 bg-sky-50 p-3 text-sky-900 dark:bg-sky-950/40 dark:text-sky-200"
        >
          Partially supported answer — check the cited sources.
        </div>
      ) : null}

      {answer ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">Answer</h2>
          <p
            lang={answerLang}
            aria-live="polite"
            aria-busy={busy}
            className="whitespace-pre-wrap leading-relaxed"
          >
            {sentences.map((sentence, index) => {
              const supporting = citationsBySentence.get(index) ?? [];
              const key = `${index}-${sentence.slice(0, 16)}`;
              if (supporting.length === 0) {
                return <span key={key}>{sentence} </span>;
              }
              // Each claim links to the span that supports it — the citation data
              // the API returns was previously received and discarded. The link is
              // the whole affordance on purpose: a hover-only highlight would be
              // unreachable by keyboard and invisible to assistive tech.
              return (
                <span key={key}>
                  {sentence}
                  <a
                    href={`#citation-${index}`}
                    aria-label={`Jump to source for sentence ${index + 1}`}
                    className="ml-0.5 align-super text-xs text-sky-700 underline dark:text-sky-300"
                  >
                    [{index + 1}]
                  </a>{" "}
                </span>
              );
            })}
          </p>

          {queryId ? (
            <div className="flex flex-col gap-2">
              <div className="flex gap-2">
                <button
                  type="button"
                  className="rounded border border-neutral-300 px-3 py-1 text-sm dark:border-neutral-700"
                  onClick={() => sendFeedback("up")}
                >
                  Helpful
                </button>
                <button
                  type="button"
                  className="rounded border border-neutral-300 px-3 py-1 text-sm dark:border-neutral-700"
                  onClick={() => sendFeedback("down")}
                >
                  Not helpful
                </button>
              </div>
              <p aria-live="polite" className="text-sm text-neutral-500 dark:text-neutral-400">
                {feedbackState === "sending" ? "Sending…" : (feedbackState ?? "")}
              </p>
            </div>
          ) : null}
        </section>
      ) : null}

      {citations.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">Sources</h2>
          <ul className="flex flex-col gap-3">
            {citations.map((c) => (
              <li
                // A citation is identified by its span within a chunk for a given
                // sentence — stable across re-renders, unlike the array position.
                key={`${c.chunkId}-${c.answerSentenceIdx}-${c.startChar}-${c.endChar}`}
                id={`citation-${c.answerSentenceIdx}`}
                className="rounded border border-neutral-300 p-3 target:border-sky-500 dark:border-neutral-700"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">
                    [{c.answerSentenceIdx + 1}] {c.documentTitle}
                  </span>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      STALENESS_TONE[c.staleness] ?? STALENESS_TONE.unknown
                    }`}
                  >
                    {STALENESS_LABEL[c.staleness] ?? STALENESS_LABEL.unknown}
                  </span>
                  <span className="text-xs text-neutral-500 dark:text-neutral-500">
                    chars {c.startChar}–{c.endChar}
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-sm text-neutral-600 dark:text-neutral-400">
                  {c.citedText}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <nav className="mt-auto pt-8 text-sm">
        <a className="underline" href="/admin">
          Document admin
        </a>
      </nav>
    </main>
  );
}
