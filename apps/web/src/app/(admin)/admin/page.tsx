"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, authHeaders, DEV_AUTH, problemDetail } from "@/lib/api";

type Collection = { id: string; name: string };
type Job = { stage: string; status: string; error: string | null };

export default function AdminPage() {
  const [user, setUser] = useState("acme-steward");
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);

  // Collections are listed and chosen, never created blind. The old flow POSTed a
  // collection named "Default" whenever local state was empty, which tripped the
  // UNIQUE(tenant_id, name) constraint on every page refresh and surfaced as an
  // opaque server error with no way to recover from the UI.
  const loadCollections = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/collections`, {
        headers: authHeaders(user),
      });
      if (!response.ok) {
        setMessage(await problemDetail(response));
        return;
      }
      const body = (await response.json()) as { data: Collection[] };
      setCollections(body.data);
      setCollectionId((current) => current || body.data[0]?.id || "");
    } catch (err) {
      setMessage(`Could not load collections: ${String(err)}`);
    }
  }, [user]);

  useEffect(() => {
    void loadCollections();
  }, [loadCollections]);

  async function pollJob(documentId: string) {
    // Upload is accepted asynchronously; without polling the user never learns
    // whether parse/embed/index actually succeeded.
    for (let attempt = 0; attempt < 15; attempt++) {
      const response = await fetch(`${API_BASE}/api/v1/documents/${documentId}/jobs`, {
        headers: authHeaders(user),
      });
      if (!response.ok) return;
      const body = (await response.json()) as { data: Job[] };
      const latest = body.data[0];
      if (!latest) return;
      setJob(latest);
      if (latest.status === "succeeded" || latest.status === "failed") return;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  async function onUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!file || busy || !collectionId) return;
    setBusy(true);
    setMessage(null);
    setJob(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("collection_id", collectionId);
      form.append("title", title || file.name);
      const response = await fetch(`${API_BASE}/api/v1/documents`, {
        method: "POST",
        headers: authHeaders(user),
        body: form,
      });
      if (!response.ok) {
        setMessage(await problemDetail(response));
        return;
      }
      const body = (await response.json()) as { document_id: string };
      setMessage("Upload accepted — ingesting…");
      setTitle("");
      setFile(null);
      await pollJob(body.document_id);
    } catch (err) {
      setMessage(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-6 py-10">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Document admin</h1>
        <p className="text-neutral-600 dark:text-neutral-400">
          Upload PDF, Markdown, or plain text.
        </p>
      </header>

      {DEV_AUTH ? (
        <label className="text-sm text-neutral-500 dark:text-neutral-400" htmlFor="dev-user">
          Dev user{" "}
          <select
            id="dev-user"
            className="ml-2 rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
            value={user}
            onChange={(e) => setUser(e.target.value)}
          >
            <option value="acme-steward">acme-steward</option>
            <option value="acme-admin">acme-admin</option>
          </select>
        </label>
      ) : null}

      <form onSubmit={onUpload} className="flex flex-col gap-3">
        <label htmlFor="title" className="text-sm font-medium">
          Document title
        </label>
        <input
          id="title"
          className="rounded border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
          placeholder="Defaults to the file name"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />

        <label htmlFor="collection" className="text-sm font-medium">
          Collection
        </label>
        <select
          id="collection"
          className="rounded border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
          value={collectionId}
          onChange={(e) => setCollectionId(e.target.value)}
        >
          {collections.length === 0 ? <option value="">No collections available</option> : null}
          {collections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>

        <label htmlFor="file" className="text-sm font-medium">
          File
        </label>
        <input
          id="file"
          type="file"
          accept=".pdf,.md,.txt,text/plain,application/pdf,text/markdown"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />

        <button
          type="submit"
          disabled={busy || !file || !collectionId}
          className="self-start rounded bg-neutral-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
      </form>

      {message ? (
        <p
          aria-live="polite"
          className="rounded border border-neutral-300 p-3 text-sm dark:border-neutral-700"
        >
          {message}
        </p>
      ) : null}

      {job ? (
        <div
          aria-live="polite"
          className={`rounded border p-3 text-sm ${
            job.status === "failed"
              ? "border-rose-400/60 text-rose-800 dark:text-rose-200"
              : job.status === "succeeded"
                ? "border-emerald-500/50 text-emerald-800 dark:text-emerald-200"
                : "border-neutral-300 dark:border-neutral-700"
          }`}
        >
          <div>
            Ingest stage <strong>{job.stage}</strong> — {job.status}
          </div>
          {job.error ? <div className="mt-1 font-mono text-xs">{job.error}</div> : null}
        </div>
      ) : null}

      <nav className="text-sm">
        <a className="underline" href="/">
          Back to chat
        </a>
      </nav>
    </main>
  );
}
