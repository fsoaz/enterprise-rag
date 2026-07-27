"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, authHeaders, DEV_AUTH, problemDetail } from "@/lib/api";
import { LocaleSwitch, useLocale } from "@/lib/i18n";

type Collection = { id: string; name: string };
type Document = {
  id: string;
  collection_id: string;
  title: string;
  language: string;
  archived_at: string | null;
  created_at: string;
  current_version_id: string | null;
};
type Job = {
  id: string;
  stage: string;
  status: string;
  error: string | null;
  attempts: number;
  created_at: string;
};

export default function AdminPage() {
  const { locale, t } = useLocale();
  const [user, setUser] = useState("acme-steward");
  const [collections, setCollections] = useState<Collection[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyDocumentId, setBusyDocumentId] = useState<string | null>(null);
  const [expandedDocumentId, setExpandedDocumentId] = useState<string | null>(null);
  const [jobsByDocument, setJobsByDocument] = useState<Record<string, Job[]>>({});

  // Collections are listed and chosen, never created blind. The old flow POSTed a
  // collection named "Default" whenever local state was empty, which tripped the
  // UNIQUE(tenant_id, name) constraint on every page refresh and surfaced as an
  // opaque server error with no way to recover from the UI.
  const loadCollections = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/collections`, {
        headers: { "Accept-Language": locale, ...authHeaders(user) },
      });
      if (!response.ok) {
        setMessage(await problemDetail(response));
        return;
      }
      const body = (await response.json()) as { data: Collection[] };
      setCollections(body.data);
      setCollectionId((current) => current || body.data[0]?.id || "");
    } catch (err) {
      setMessage(t("loadCollectionsFailed", { detail: String(err) }));
    }
  }, [locale, t, user]);

  const loadDocuments = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/documents?limit=100`, {
        headers: { "Accept-Language": locale, ...authHeaders(user) },
      });
      if (!response.ok) {
        setMessage(await problemDetail(response));
        return;
      }
      const body = (await response.json()) as { data: Document[] };
      setDocuments(body.data);
    } catch (err) {
      setMessage(t("loadDocumentsFailed", { detail: String(err) }));
    }
  }, [locale, t, user]);

  useEffect(() => {
    void Promise.all([loadCollections(), loadDocuments()]);
  }, [loadCollections, loadDocuments]);

  async function pollJob(documentId: string) {
    // Upload is accepted asynchronously; without polling the user never learns
    // whether parse/embed/index actually succeeded.
    for (let attempt = 0; attempt < 15; attempt++) {
      const response = await fetch(`${API_BASE}/api/v1/documents/${documentId}/jobs`, {
        headers: { "Accept-Language": locale, ...authHeaders(user) },
      });
      if (!response.ok) {
        setMessage(await problemDetail(response));
        return;
      }
      const body = (await response.json()) as { data: Job[] };
      const latest = body.data[0];
      if (!latest) {
        setMessage(t("noJob"));
        return;
      }
      setJob(latest);
      if (latest.status === "succeeded" || latest.status === "failed") return;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    setMessage(t("stillProcessing"));
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
        headers: { "Accept-Language": locale, ...authHeaders(user) },
        body: form,
      });
      if (!response.ok) {
        setMessage(await problemDetail(response));
        return;
      }
      const body = (await response.json()) as { document_id: string };
      setMessage(t("uploadAccepted"));
      setTitle("");
      setFile(null);
      await loadDocuments();
      await pollJob(body.document_id);
      await loadDocuments();
    } catch (err) {
      setMessage(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleJobs(documentId: string) {
    if (expandedDocumentId === documentId) {
      setExpandedDocumentId(null);
      return;
    }
    setExpandedDocumentId(documentId);
    if (jobsByDocument[documentId]) return;
    try {
      const response = await fetch(`${API_BASE}/api/v1/documents/${documentId}/jobs`, {
        headers: { "Accept-Language": locale, ...authHeaders(user) },
      });
      if (!response.ok) {
        setMessage(await problemDetail(response));
        return;
      }
      const body = (await response.json()) as { data: Job[] };
      setJobsByDocument((current) => ({ ...current, [documentId]: body.data }));
    } catch (err) {
      setMessage(t("loadHistoryFailed", { detail: String(err) }));
    }
  }

  async function changeArchiveState(document: Document) {
    if (busyDocumentId) return;
    setBusyDocumentId(document.id);
    setMessage(null);
    const action = document.archived_at ? "unarchive" : "archive";
    try {
      const response = await fetch(`${API_BASE}/api/v1/documents/${document.id}/${action}`, {
        method: "POST",
        headers: { "Accept-Language": locale, ...authHeaders(user) },
      });
      if (!response.ok) {
        setMessage(await problemDetail(response));
        return;
      }
      const updated = (await response.json()) as Document;
      setDocuments((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setMessage(updated.archived_at ? t("archivedMessage") : t("restoredMessage"));
    } catch (err) {
      setMessage(t("updateDocumentFailed", { detail: String(err) }));
    } finally {
      setBusyDocumentId(null);
    }
  }

  const collectionNames = new Map(
    collections.map((collection) => [collection.id, collection.name]),
  );

  return (
    <>
      <a href="#main-content" className="sr-only focus:not-sr-only">
        {t("skip")}
      </a>
      <main
        id="main-content"
        className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-6 py-10"
      >
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">{t("documentAdmin")}</h1>
          <p className="text-neutral-600 dark:text-neutral-400">{t("adminDescription")}</p>
          {DEV_AUTH ? <LocaleSwitch /> : null}
        </header>

        {DEV_AUTH ? (
          <label className="text-sm text-neutral-500 dark:text-neutral-400" htmlFor="dev-user">
            {t("devUser")}{" "}
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
            {t("documentTitle")}
          </label>
          <input
            id="title"
            className="rounded border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
            placeholder={t("titlePlaceholder")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />

          <label htmlFor="collection" className="text-sm font-medium">
            {t("collection")}
          </label>
          <select
            id="collection"
            className="rounded border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
            value={collectionId}
            onChange={(e) => setCollectionId(e.target.value)}
          >
            {collections.length === 0 ? <option value="">{t("noCollections")}</option> : null}
            {collections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>

          <label htmlFor="file" className="text-sm font-medium">
            {t("file")}
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
            {busy ? t("uploading") : t("upload")}
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
              {t("ingestStage")} <strong>{job.stage}</strong> — {job.status}
            </div>
            {job.error ? <div className="mt-1 font-mono text-xs">{job.error}</div> : null}
          </div>
        ) : null}

        <section aria-labelledby="document-list-heading" className="flex flex-col gap-3">
          <div className="flex items-end justify-between gap-3">
            <div>
              <h2 id="document-list-heading" className="text-xl font-semibold">
                {t("documents")}
              </h2>
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                {t("documentsDescription")}
              </p>
            </div>
            <button
              type="button"
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm dark:border-neutral-700"
              onClick={() => void loadDocuments()}
            >
              {t("refresh")}
            </button>
          </div>

          {documents.length === 0 ? (
            <p className="rounded border border-dashed border-neutral-300 p-4 text-sm text-neutral-600 dark:border-neutral-700 dark:text-neutral-400">
              {t("noDocuments")}
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {documents.map((document) => {
                const documentJobs = jobsByDocument[document.id];
                const expanded = expandedDocumentId === document.id;
                return (
                  <li
                    key={document.id}
                    className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-medium">{document.title}</h3>
                          {document.archived_at ? (
                            <span className="rounded-full border border-amber-500/50 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-300">
                              {t("archived")}
                            </span>
                          ) : (
                            <span className="rounded-full border border-emerald-500/40 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-300">
                              {t("active")}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-neutral-500">
                          {collectionNames.get(document.collection_id) ?? t("unknownCollection")} ·{" "}
                          {document.language.toUpperCase()} · {t("added")}{" "}
                          {new Date(document.created_at).toLocaleDateString(
                            locale === "pt" ? "pt-BR" : "en",
                          )}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          className="rounded border border-neutral-300 px-3 py-1.5 text-sm dark:border-neutral-700"
                          aria-expanded={expanded}
                          onClick={() => void toggleJobs(document.id)}
                        >
                          {expanded ? t("hideJobs") : t("viewJobs")}
                        </button>
                        <button
                          type="button"
                          className="rounded border border-neutral-300 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-neutral-700"
                          disabled={busyDocumentId === document.id}
                          onClick={() => void changeArchiveState(document)}
                        >
                          {busyDocumentId === document.id
                            ? t("updating")
                            : document.archived_at
                              ? t("restore")
                              : t("archive")}
                        </button>
                      </div>
                    </div>

                    {expanded ? (
                      <div className="mt-3 border-t border-neutral-200 pt-3 text-sm dark:border-neutral-800">
                        {!documentJobs ? (
                          <p role="status">{t("loadingHistory")}</p>
                        ) : documentJobs.length === 0 ? (
                          <p>{t("noJobs")}</p>
                        ) : (
                          <ol className="flex flex-col gap-2">
                            {documentJobs.map((historyJob) => (
                              <li key={historyJob.id} className="flex flex-col">
                                <span>
                                  <strong>{historyJob.stage}</strong> — {historyJob.status}
                                  {historyJob.attempts > 1
                                    ? ` (${t("attempts", { count: historyJob.attempts })})`
                                    : ""}
                                </span>
                                {historyJob.error ? (
                                  <span className="font-mono text-xs text-rose-700 dark:text-rose-300">
                                    {historyJob.error}
                                  </span>
                                ) : null}
                              </li>
                            ))}
                          </ol>
                        )}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <nav className="text-sm">
          <a className="underline" href="/">
            {t("backToChat")}
          </a>
        </nav>
      </main>
    </>
  );
}
