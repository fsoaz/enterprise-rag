"use client";

import { useEffect, useState } from "react";
import { DEV_AUTH } from "@/lib/api";
import { LocaleSwitch, useLocale } from "@/lib/i18n";

type SessionUser = {
  email: string;
  external_subject: string;
  roles: string[];
};

type Session =
  | { status: "loading" }
  | { status: "anonymous"; error?: string }
  | { status: "authenticated"; user: SessionUser };

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { t } = useLocale();
  const [session, setSession] = useState<Session>(
    DEV_AUTH
      ? { status: "authenticated", user: { email: "", external_subject: "", roles: [] } }
      : { status: "loading" },
  );

  useEffect(() => {
    if (DEV_AUTH) return;
    let active = true;
    const authError = new URLSearchParams(window.location.search).get("auth_error");
    if (authError) {
      setSession({ status: "anonymous", error: authError });
      return;
    }
    fetch("/api/auth/session", { cache: "no-store" })
      .then(async (response) => {
        if (!active) return;
        if (!response.ok) {
          setSession({ status: "anonymous" });
          return;
        }
        const body = (await response.json()) as { user: SessionUser };
        setSession({ status: "authenticated", user: body.user });
      })
      .catch(() => {
        if (active) setSession({ status: "anonymous", error: t("authUnavailable") });
      });
    return () => {
      active = false;
    };
  }, [t]);

  if (DEV_AUTH) return children;
  if (session.status === "loading") {
    return (
      <main className="grid min-h-screen place-items-center px-6">
        <p role="status">{t("authChecking")}</p>
      </main>
    );
  }
  if (session.status === "anonymous") {
    return (
      <main className="grid min-h-screen place-items-center px-6">
        <section className="flex max-w-md flex-col gap-4 text-center">
          <h1 className="text-3xl font-semibold tracking-tight">Enterprise RAG</h1>
          <p className="text-neutral-600 dark:text-neutral-400">{t("authDescription")}</p>
          {session.error ? (
            <p role="alert" className="text-rose-700 dark:text-rose-300">
              {session.error}
            </p>
          ) : null}
          <a
            className="rounded bg-neutral-900 px-4 py-2 text-white dark:bg-neutral-100 dark:text-neutral-900"
            href="/api/auth/login"
          >
            {t("signIn")}
          </a>
        </section>
      </main>
    );
  }

  return (
    <>
      <header className="sticky top-0 z-50 flex max-w-full flex-wrap items-center justify-end gap-3 border-b border-neutral-300 bg-white/95 px-4 py-1.5 text-xs dark:border-neutral-700 dark:bg-neutral-950/95">
        <LocaleSwitch />
        <span className="max-w-[12rem] truncate sm:max-w-[16rem]">{session.user.email}</span>
        <form action="/api/auth/logout" method="post">
          <button type="submit" className="underline">
            {t("signOut")}
          </button>
        </form>
      </header>
      {children}
    </>
  );
}
