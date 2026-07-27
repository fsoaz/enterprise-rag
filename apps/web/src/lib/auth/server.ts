import "server-only";

import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import type { NextRequest, NextResponse } from "next/server";

export const ACCESS_COOKIE = "erag_access";
export const REFRESH_COOKIE = "erag_refresh";
export const ID_COOKIE = "erag_id";
export const EXPIRES_COOKIE = "erag_access_expires";
export const STATE_COOKIE = "erag_oauth_state";
export const VERIFIER_COOKIE = "erag_pkce_verifier";
export const RETURN_TO_COOKIE = "erag_return_to";

type OidcMetadata = {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
};

export type TokenSet = {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in?: number;
};

let metadataPromise: Promise<OidcMetadata> | null = null;

function requiredEnv(name: string, fallback?: string): string {
  const value = process.env[name]?.trim() || fallback;
  if (!value) throw new Error(`${name} is required when NEXT_PUBLIC_DEV_AUTH is false`);
  return value.replace(/\/$/, "");
}

export function appBaseUrl(): string {
  return requiredEnv("APP_BASE_URL", "http://localhost:3000");
}

export function apiBaseUrl(): string {
  return requiredEnv("API_BASE_URL", process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000");
}

export function callbackUrl(): string {
  return `${appBaseUrl()}/api/auth/callback`;
}

export function safeReturnTo(value: string | null): string {
  if (!value?.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}

function internalUrl(url: string): string {
  const internalBase = process.env.OIDC_INTERNAL_BASE_URL?.trim().replace(/\/$/, "");
  if (!internalBase) return url;
  const publicIssuer = new URL(requiredEnv("OIDC_ISSUER"));
  const target = new URL(url);
  if (target.origin !== publicIssuer.origin) {
    throw new Error("OIDC metadata returned an endpoint outside the configured issuer origin");
  }
  return `${internalBase}${target.pathname}${target.search}`;
}

export async function oidcMetadata(): Promise<OidcMetadata> {
  if (!metadataPromise) {
    metadataPromise = (async () => {
      const issuer = requiredEnv("OIDC_ISSUER");
      const discoveryUrl = internalUrl(`${issuer}/.well-known/openid-configuration`);
      const response = await fetch(discoveryUrl, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`OIDC discovery failed (${response.status})`);
      }
      const metadata = (await response.json()) as Partial<OidcMetadata>;
      if (
        metadata.issuer !== issuer ||
        !metadata.authorization_endpoint ||
        !metadata.token_endpoint
      ) {
        throw new Error("OIDC discovery response does not match the configured issuer");
      }
      return metadata as OidcMetadata;
    })().catch((error: unknown) => {
      metadataPromise = null;
      throw error;
    });
  }
  return metadataPromise;
}

export function randomUrlSafe(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

export function pkceChallenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

export function equalState(expected: string | undefined, received: string | null): boolean {
  if (!expected || !received) return false;
  const left = Buffer.from(expected);
  const right = Buffer.from(received);
  return left.length === right.length && timingSafeEqual(left, right);
}

function clientCredentials(body: URLSearchParams): Headers {
  const headers = new Headers({ "Content-Type": "application/x-www-form-urlencoded" });
  const clientId = requiredEnv("OIDC_CLIENT_ID", "enterprise-rag-web");
  const clientSecret = process.env.OIDC_CLIENT_SECRET?.trim();
  if (clientSecret) {
    headers.set(
      "Authorization",
      `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString("base64")}`,
    );
  } else {
    body.set("client_id", clientId);
  }
  return headers;
}

async function requestTokens(body: URLSearchParams): Promise<TokenSet> {
  const metadata = await oidcMetadata();
  const response = await fetch(internalUrl(metadata.token_endpoint), {
    method: "POST",
    headers: clientCredentials(body),
    body,
    cache: "no-store",
  });
  const payload = (await response.json()) as Partial<TokenSet> & {
    error?: string;
    error_description?: string;
  };
  if (
    !response.ok ||
    !payload.access_token ||
    payload.token_type?.toLowerCase() !== "bearer" ||
    typeof payload.expires_in !== "number"
  ) {
    const detail = payload.error_description ?? payload.error ?? `HTTP ${response.status}`;
    throw new Error(`OIDC token request failed: ${detail}`);
  }
  return payload as TokenSet;
}

export async function exchangeCode(code: string, verifier: string): Promise<TokenSet> {
  return requestTokens(
    new URLSearchParams({
      grant_type: "authorization_code",
      code,
      code_verifier: verifier,
      redirect_uri: callbackUrl(),
    }),
  );
}

export async function refreshTokens(refreshToken: string): Promise<TokenSet> {
  return requestTokens(
    new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    }),
  );
}

function secureCookies(): boolean {
  const configured = process.env.AUTH_COOKIE_SECURE?.trim();
  return configured ? configured.toLowerCase() === "true" : appBaseUrl().startsWith("https://");
}

const cookieBase = () =>
  ({
    httpOnly: true,
    secure: secureCookies(),
    sameSite: "lax" as const,
    path: "/",
  }) as const;

export function setTokenCookies(response: NextResponse, tokens: TokenSet): void {
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...cookieBase(),
    maxAge: Math.max(tokens.expires_in, 1),
  });
  response.cookies.set(EXPIRES_COOKIE, String(Date.now() + tokens.expires_in * 1000), {
    ...cookieBase(),
    maxAge: Math.max(tokens.expires_in, 1),
  });
  if (tokens.refresh_token) {
    response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
      ...cookieBase(),
      maxAge: Math.max(tokens.refresh_expires_in ?? 30 * 24 * 60 * 60, 1),
    });
  }
  if (tokens.id_token) {
    response.cookies.set(ID_COOKIE, tokens.id_token, {
      ...cookieBase(),
      maxAge: Math.max(tokens.refresh_expires_in ?? tokens.expires_in, 1),
    });
  }
}

export function clearAuthCookies(response: NextResponse): void {
  for (const name of [
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    ID_COOKIE,
    EXPIRES_COOKIE,
    STATE_COOKIE,
    VERIFIER_COOKIE,
    RETURN_TO_COOKIE,
  ]) {
    response.cookies.set(name, "", { ...cookieBase(), maxAge: 0 });
  }
}

export function tokenCookies(request: NextRequest): {
  accessToken?: string;
  refreshToken?: string;
  expiresAt: number;
} {
  return {
    accessToken: request.cookies.get(ACCESS_COOKIE)?.value,
    refreshToken: request.cookies.get(REFRESH_COOKIE)?.value,
    expiresAt: Number(request.cookies.get(EXPIRES_COOKIE)?.value ?? 0),
  };
}

export function setTransientCookie(response: NextResponse, name: string, value: string): void {
  response.cookies.set(name, value, { ...cookieBase(), maxAge: 10 * 60 });
}

export async function accessTokenFor(
  request: NextRequest,
): Promise<{ accessToken: string | null; refreshed?: TokenSet }> {
  const tokens = tokenCookies(request);
  if (tokens.accessToken && tokens.expiresAt > Date.now() + 15_000) {
    return { accessToken: tokens.accessToken };
  }
  if (!tokens.refreshToken) return { accessToken: tokens.accessToken ?? null };
  try {
    const refreshed = await refreshTokens(tokens.refreshToken);
    return { accessToken: refreshed.access_token, refreshed };
  } catch {
    return { accessToken: null };
  }
}
