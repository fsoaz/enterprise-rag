"use client";

import { useState } from "react";

type Citation = {
  document_title: string;
  cited_text: string;
  chunk_id: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function ChatPage() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [verdict, setVerdict] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [queryId, setQueryId] = useState<string | null>(null);
  const [user, setUser] = useState("acme-member");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;
    setBusy(true);
    setAnswer("");
    setCitations([]);
    setVerdict(null);
    setQueryId(null);
    setStatus("retrieving");

    try {
      const response = await fetch(`${API_BASE}/api/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Dev-User": user,
        },
        body: JSON.stringify({ question, stream: true }),
      });
      if (!response.ok || !response.body) {
        setAnswer(`Error ${response.status}`);
        setBusy(false);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let eventName = "message";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n");
        buffer = parts.pop() ?? "";
        for (const line of parts) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const data = JSON.parse(line.slice(5).trim()) as Record<string, unknown>;
            if (eventName === "token") {
              setAnswer((prev) => prev + String(data.text ?? ""));
            } else if (eventName === "citation") {
              setCitations((prev) => [
                ...prev,
                {
                  document_title: String(data.document_title ?? "Source"),
                  cited_text: String(data.cited_text ?? ""),
                  chunk_id: String(data.chunk_id ?? ""),
                },
              ]);
            } else if (eventName === "status") {
              setStatus(String(data.stage ?? ""));
            } else if (eventName === "verdict") {
              setVerdict(String(data.groundedness ?? ""));
            } else if (eventName === "done") {
              setQueryId(String(data.query_id ?? ""));
              setStatus(null);
            }
          }
        }
      }
    } catch (err) {
      setAnswer(`Request failed: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  }

  async function sendFeedback(rating: "up" | "down") {
    if (!queryId) return;
    await fetch(`${API_BASE}/api/v1/feedback`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Dev-User": user,
      },
      body: JSON.stringify({ query_id: queryId, rating }),
    });
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Enterprise RAG</h1>
        <p className="text-neutral-600">Ask a question grounded in your documents.</p>
        <label className="text-sm text-neutral-500">
          Dev user{" "}
          <select
            className="ml-2 rounded border px-2 py-1"
            value={user}
            onChange={(e) => setUser(e.target.value)}
          >
            <option value="acme-member">acme-member</option>
            <option value="acme-steward">acme-steward</option>
            <option value="acme-viewer">acme-viewer</option>
            <option value="globex-admin">globex-admin</option>
          </select>
        </label>
      </header>

      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <textarea
          className="min-h-24 w-full rounded border border-neutral-300 p-3"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask in Portuguese or English…"
        />
        <button
          type="submit"
          disabled={busy}
          className="self-start rounded bg-neutral-900 px-4 py-2 text-white disabled:opacity-50"
        >
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>

      {status ? <p className="text-sm text-neutral-500">Status: {status}</p> : null}

      {verdict === "unsupported" ? (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-amber-900">
          The system abstained — corpus does not support a grounded answer.
        </div>
      ) : null}
      {verdict === "partial" ? (
        <div className="rounded border border-sky-300 bg-sky-50 p-3 text-sky-900">
          Partially supported answer.
        </div>
      ) : null}

      {answer ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">Answer</h2>
          <p className="whitespace-pre-wrap leading-relaxed">{answer}</p>
          {queryId ? (
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded border px-3 py-1 text-sm"
                onClick={() => sendFeedback("up")}
              >
                Helpful
              </button>
              <button
                type="button"
                className="rounded border px-3 py-1 text-sm"
                onClick={() => sendFeedback("down")}
              >
                Not helpful
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {citations.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">Sources</h2>
          <ul className="flex flex-col gap-3">
            {citations.map((c) => (
              <li key={`${c.chunk_id}-${c.cited_text.slice(0, 24)}`} className="rounded border p-3">
                <div className="text-sm font-medium">{c.document_title}</div>
                <p className="mt-1 text-sm text-neutral-600">{c.cited_text}</p>
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
