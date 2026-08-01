"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE,
  authHeaders,
  type ChatMessage,
  type ChatRequest,
  type Citation,
  DEV_AUTH,
  problemDetail,
  type Verdict,
} from "@/lib/api";
import { LocaleSwitch, useLocale } from "@/lib/i18n";
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
  is_suspect?: boolean;
};

type CompletedTurn = {
  id: string;
  question: string;
  answer: string;
};

/** Split an answer into sentences, keeping each sentence's index. */
const ABBREV_BEFORE_PERIOD = /\b(?:Dr|Mr|Mrs|Ms|Sec|vs|etc|Inc|Ltd|Jr|Sr)\.$/i;

function splitSentences(text: string): string[] {
  const stripped = text.trim();
  if (!stripped) return [];
  const boundary = /(?<=[.!?])\s+/g;
  const parts: string[] = [];
  let last = 0;
  let match = boundary.exec(stripped);
  while (match !== null) {
    if (ABBREV_BEFORE_PERIOD.test(stripped.slice(0, match.index).replace(/\s+$/, ""))) {
      match = boundary.exec(stripped);
      continue;
    }
    const part = stripped.slice(last, match.index);
    if (part.trim()) parts.push(part);
    last = match.index + match[0].length;
    match = boundary.exec(stripped);
  }
  const tail = stripped.slice(last);
  if (tail.trim()) parts.push(tail);
  return parts;
}

const STALENESS_TONE: Record<string, string> = {
  fresh: "border-emerald-500/40 text-emerald-700 dark:text-emerald-300",
  stale: "border-amber-500/50 text-amber-700 dark:text-amber-300",
  superseded: "border-rose-500/50 text-rose-700 dark:text-rose-300",
  unknown: "border-neutral-400/40 text-neutral-600 dark:text-neutral-400",
};

export default function ChatPage() {
  const { locale, t } = useLocale();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [queryId, setQueryId] = useState<string | null>(null);
  const [user, setUser] = useState("acme-member");
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedbackState, setFeedbackState] = useState<string | null>(null);
  const [feedbackRating, setFeedbackRating] = useState<"up" | "down" | null>(null);
  const [answerLang, setAnswerLang] = useState("en");
  const [completedTurns, setCompletedTurns] = useState<CompletedTurn[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const answerRef = useRef("");

  // Abort any in-flight stream when the component goes away, so the reader loop
  // does not keep running (and setting state) after unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const sentences = useMemo(() => splitSentences(answer), [answer]);
  const renderedCitations = useMemo(
    () =>
      citations.filter(
        (citation) =>
          citation.answerSentenceIdx === -1 ||
          (citation.answerSentenceIdx >= 0 && citation.answerSentenceIdx < sentences.length),
      ),
    [citations, sentences.length],
  );

  /** Citations grouped by the answer sentence they support. */
  const citationsBySentence = useMemo(() => {
    const map = new Map<number, Citation[]>();
    for (const citation of renderedCitations) {
      const list = map.get(citation.answerSentenceIdx) ?? [];
      list.push(citation);
      map.set(citation.answerSentenceIdx, list);
    }
    return map;
  }, [renderedCitations]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setStatus(null);
    setCancelled(true);
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const submittedQuestion = question.trim();
    const turnId = `${Date.now()}-${completedTurns.length}`;
    const messages: ChatMessage[] = [
      ...completedTurns.slice(-5).flatMap((turn): ChatMessage[] => [
        { role: "user", content: turn.question },
        { role: "assistant", content: turn.answer.slice(0, 16_000) },
      ]),
      { role: "user", content: submittedQuestion },
    ];
    const requestBody: ChatRequest = { messages, stream: true, strategy: "hybrid_rrf" };

    setBusy(true);
    setCancelled(false);
    setAnswer("");
    answerRef.current = "";
    setCitations([]);
    setVerdict(null);
    setQueryId(null);
    setError(null);
    setFeedbackState(null);
    setFeedbackRating(null);
    setStatus("retrieving");
    // Portuguese answers must not be announced with English phonetics.
    setAnswerLang(
      /[ãáàâçéêíóôõú]|\b(qual|quais|como|quando|onde|prazo|pol[ií]tica|documento)\b/i.test(question)
        ? "pt"
        : "en",
    );

    try {
      const response = await fetch(`${API_BASE}/api/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept-Language": locale,
          ...authHeaders(user),
        },
        body: JSON.stringify(requestBody),
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
      if (answerRef.current) {
        setCompletedTurns((previous) => [
          ...previous,
          { id: turnId, question: submittedQuestion, answer: answerRef.current },
        ]);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(t("requestFailed", { detail: String(err) }));
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
      const text = String(payload.text ?? "");
      answerRef.current += text;
      setAnswer((prev) => prev + text);
    } else if (name === "citation") {
      const c = payload as CitationEvent;
      setCitations((prev) => [
        ...prev,
        {
          chunkId: String(c.chunk_id ?? ""),
          documentVersionId: String(c.document_version_id ?? ""),
          documentTitle: String(c.document_title ?? t("source")),
          citedText: String(c.cited_text ?? ""),
          startChar: Number(c.start_char ?? 0),
          endChar: Number(c.end_char ?? 0),
          answerSentenceIdx: Number(c.answer_sentence_idx ?? 0),
          staleness: String(c.staleness ?? "unknown"),
          isSuspect: Boolean(c.is_suspect),
        },
      ]);
    } else if (name === "status") {
      setStatus(String(payload.stage ?? ""));
    } else if (name === "verdict") {
      setVerdict(String(payload.groundedness ?? "") as Verdict);
    } else if (name === "done") {
      setQueryId(String(payload.query_id ?? ""));
      setStatus(null);
    } else if (name === "error") {
      setError(String(payload.detail ?? t("streamFailed")));
    }
  }

  async function sendFeedback(rating: "up" | "down") {
    if (!queryId || feedbackState === "sending") return;
    setFeedbackState("sending");
    setFeedbackRating(rating);
    try {
      const response = await fetch(`${API_BASE}/api/v1/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept-Language": locale,
          ...authHeaders(user),
        },
        body: JSON.stringify({ query_id: queryId, rating }),
      });
      // Silent failure left users believing feedback was recorded when it was not.
      setFeedbackState(response.ok ? t("feedbackThanks") : await problemDetail(response));
    } catch (err) {
      setFeedbackState(t("feedbackFailed", { detail: String(err) }));
    }
  }

  return (
    <>
      <a href="#main-content" className="sr-only focus:not-sr-only">
        {t("skip")}
      </a>
      <main
        id="main-content"
        className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10"
      >
        <header className="flex flex-col gap-2">
          <h1 className="text-3xl font-semibold tracking-tight">Enterprise RAG</h1>
          <p className="text-neutral-600 dark:text-neutral-400">{t("chatDescription")}</p>
          {DEV_AUTH ? <LocaleSwitch /> : null}
          {DEV_AUTH ? (
            <label className="text-sm text-neutral-500 dark:text-neutral-400" htmlFor="dev-user">
              {t("devUser")}{" "}
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

        {completedTurns.length > (busy || !answer ? 0 : 1) ? (
          <section aria-labelledby="conversation-heading" className="flex flex-col gap-3">
            <h2 id="conversation-heading" className="text-lg font-medium">
              {t("conversation")}
            </h2>
            <ol className="flex flex-col gap-4">
              {completedTurns.slice(0, busy || !answer ? undefined : -1).map((turn) => (
                <li
                  key={turn.id}
                  className="flex flex-col gap-2 border-l-2 border-neutral-200 pl-4 dark:border-neutral-800"
                >
                  <p>
                    <strong>{t("you")}:</strong> {turn.question}
                  </p>
                  <p className="whitespace-pre-wrap text-neutral-700 dark:text-neutral-300">
                    <strong>{t("assistant")}:</strong> {turn.answer}
                  </p>
                </li>
              ))}
            </ol>
          </section>
        ) : null}

        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <label htmlFor="question" className="text-sm font-medium">
            {t("question")}
          </label>
          <textarea
            id="question"
            className="min-h-24 w-full rounded border border-neutral-300 bg-transparent p-3 dark:border-neutral-700"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t("questionPlaceholder")}
          />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={busy || !question.trim()}
              className="self-start rounded bg-neutral-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
            >
              {busy ? t("thinking") : t("ask")}
            </button>
            {busy ? (
              <button
                type="button"
                onClick={stop}
                className="self-start rounded border border-neutral-300 px-4 py-2 dark:border-neutral-700"
              >
                {t("stop")}
              </button>
            ) : null}
          </div>
        </form>

        {status ? (
          <p
            className="text-sm text-neutral-500 dark:text-neutral-400"
            aria-live="polite"
            aria-atomic="true"
          >
            {status === "retrieving"
              ? t("retrieving")
              : status === "verifying"
                ? t("verifying")
                : t("generating")}
          </p>
        ) : null}
        <p role="status" className="sr-only">
          {cancelled && answer
            ? t("answerCancelled")
            : !busy && answer
              ? t("answerReady", { count: renderedCitations.length })
              : ""}
        </p>

        {cancelled && answer ? (
          <div
            role="status"
            className="rounded border border-neutral-400/60 bg-neutral-50 p-3 text-neutral-800 dark:bg-neutral-900/40 dark:text-neutral-200"
          >
            {t("answerCancelled")}
          </div>
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
            {t("unsupported")}
          </div>
        ) : null}
        {verdict === "partial" ? (
          <div
            role="status"
            className="rounded border border-sky-400/60 bg-sky-50 p-3 text-sky-900 dark:bg-sky-950/40 dark:text-sky-200"
          >
            {t("partial")}
          </div>
        ) : null}

        {answer ? (
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">{t("answer")}</h2>
            <p lang={answerLang} aria-busy={busy} className="whitespace-pre-wrap leading-relaxed">
              {sentences.map((sentence, index) => {
                const supporting = (citationsBySentence.get(index) ?? []).filter(
                  (citation) => citation.answerSentenceIdx >= 0,
                );
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
                    {supporting.map((citation) => {
                      const sourceNumber = renderedCitations.indexOf(citation) + 1;
                      return (
                        <a
                          key={`${citation.chunkId}-${citation.startChar}-${citation.endChar}-${sourceNumber}`}
                          href={`#citation-${sourceNumber}`}
                          aria-label={t("jumpSource", { number: sourceNumber })}
                          className="ml-0.5 align-super text-xs text-sky-700 underline dark:text-sky-300"
                        >
                          [{sourceNumber}]
                        </a>
                      );
                    })}{" "}
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
                    aria-pressed={feedbackRating === "up"}
                  >
                    {t("helpful")}
                  </button>
                  <button
                    type="button"
                    className="rounded border border-neutral-300 px-3 py-1 text-sm dark:border-neutral-700"
                    onClick={() => sendFeedback("down")}
                    aria-pressed={feedbackRating === "down"}
                  >
                    {t("notHelpful")}
                  </button>
                </div>
                <p aria-live="polite" className="text-sm text-neutral-500 dark:text-neutral-400">
                  {feedbackState === "sending" ? t("sending") : (feedbackState ?? "")}
                </p>
              </div>
            ) : null}
          </section>
        ) : null}

        {renderedCitations.length > 0 ? (
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">{t("sources")}</h2>
            <ul className="flex flex-col gap-3">
              {renderedCitations.map((c, index) => (
                <li
                  // The rendered key follows the cited span, not a sentence number.
                  key={`${c.chunkId}-${c.documentVersionId}-${c.startChar}-${c.endChar}`}
                  id={`citation-${index + 1}`}
                  className="rounded border border-neutral-300 p-3 target:border-sky-500 dark:border-neutral-700"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">
                      [{index + 1}] {c.documentTitle}
                    </span>
                    {c.isSuspect ? (
                      <span className="rounded border border-amber-600 px-2 py-0.5 text-xs text-amber-800 dark:border-amber-400 dark:text-amber-200">
                        {t("unverifiedSource")}
                      </span>
                    ) : null}
                    <span
                      className={`rounded-full border px-2 py-0.5 text-xs ${
                        STALENESS_TONE[c.staleness] ?? STALENESS_TONE.unknown
                      }`}
                    >
                      {c.staleness === "fresh"
                        ? t("stalenessFresh")
                        : c.staleness === "stale"
                          ? t("stalenessStale")
                          : c.staleness === "superseded"
                            ? t("stalenessSuperseded")
                            : t("stalenessUnknown")}
                    </span>
                    <span className="text-xs text-neutral-500 dark:text-neutral-500">
                      {t("chars")} {c.startChar}–{c.endChar}
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
            {t("documentAdmin")}
          </a>
        </nav>
      </main>
    </>
  );
}
