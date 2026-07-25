"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function AdminPage() {
  const [user, setUser] = useState("acme-steward");
  const [collectionId, setCollectionId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function ensureCollection(): Promise<string> {
    if (collectionId) return collectionId;
    const response = await fetch(`${API_BASE}/api/v1/collections`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Dev-User": user,
      },
      body: JSON.stringify({
        name: "Default",
        description: "Uploaded from admin UI",
      }),
    });
    if (!response.ok) {
      throw new Error(`collection create failed: ${response.status}`);
    }
    const data = (await response.json()) as { id: string };
    setCollectionId(data.id);
    return data.id;
  }

  async function onUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const colId = await ensureCollection();
      const form = new FormData();
      form.append("file", file);
      form.append("collection_id", colId);
      form.append("title", title || file.name);
      const response = await fetch(`${API_BASE}/api/v1/documents`, {
        method: "POST",
        headers: { "X-Dev-User": user },
        body: form,
      });
      const body = await response.text();
      if (!response.ok) {
        setMessage(`Upload failed (${response.status}): ${body}`);
      } else {
        setMessage(`Accepted: ${body}`);
        setFile(null);
        setTitle("");
      }
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
        <p className="text-neutral-600">Upload PDF, Markdown, or plain text.</p>
      </header>

      <label className="text-sm text-neutral-500">
        Dev user{" "}
        <select
          className="ml-2 rounded border px-2 py-1"
          value={user}
          onChange={(e) => setUser(e.target.value)}
        >
          <option value="acme-steward">acme-steward</option>
          <option value="acme-admin">acme-admin</option>
        </select>
      </label>

      <form onSubmit={onUpload} className="flex flex-col gap-3">
        <input
          className="rounded border px-3 py-2"
          placeholder="Document title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <input
          className="rounded border px-3 py-2"
          placeholder="Collection ID (optional — created if empty)"
          value={collectionId}
          onChange={(e) => setCollectionId(e.target.value)}
        />
        <input
          type="file"
          accept=".pdf,.md,.txt,text/plain,application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button
          type="submit"
          disabled={busy || !file}
          className="self-start rounded bg-neutral-900 px-4 py-2 text-white disabled:opacity-50"
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
      </form>

      {message ? (
        <pre className="overflow-x-auto rounded border bg-neutral-50 p-3 text-xs">{message}</pre>
      ) : null}

      <nav className="text-sm">
        <a className="underline" href="/">
          Back to chat
        </a>
      </nav>
    </main>
  );
}
