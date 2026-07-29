import { type NextRequest, NextResponse } from "next/server";
import {
  accessTokenFor,
  apiBaseUrl,
  clearAuthCookies,
  refreshTokens,
  setTokenCookies,
  type TokenSet,
  tokenCookies,
} from "@/lib/auth/server";
import { sameOriginMutation } from "@/lib/same-origin";

type RouteContext = { params: Promise<{ path: string[] }> };

const HOP_BY_HOP = new Set([
  "connection",
  "content-length",
  "cookie",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function requestHeaders(request: NextRequest, accessToken: string): Headers {
  const headers = new Headers();
  for (const [name, value] of request.headers) {
    if (!HOP_BY_HOP.has(name.toLowerCase()) && name.toLowerCase() !== "authorization") {
      if (name.toLowerCase() === "origin" || name.toLowerCase() === "referer") continue;
      headers.set(name, value);
    }
  }
  headers.set("Authorization", `Bearer ${accessToken}`);
  headers.set("Accept-Encoding", "identity");
  return headers;
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  for (const [name, value] of upstream.headers) {
    if (!HOP_BY_HOP.has(name.toLowerCase()) && name.toLowerCase() !== "set-cookie") {
      headers.set(name, value);
    }
  }
  headers.set("Cache-Control", "no-store, private");
  return headers;
}

async function callApi(
  request: NextRequest,
  path: string[],
  accessToken: string,
  body: ArrayBuffer | undefined,
): Promise<Response> {
  const target = new URL(`${apiBaseUrl()}/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;
  return fetch(target, {
    method: request.method,
    headers: requestHeaders(request, accessToken),
    body,
    cache: "no-store",
    signal: request.signal,
  });
}

async function proxy(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  if (!sameOriginMutation(request)) {
    return NextResponse.json({ detail: "Cross-site request rejected" }, { status: 403 });
  }
  const { path } = await context.params;
  // Buffer once so a request can be retried after refreshing an access token.
  // Passing request.body directly would lock the stream on the first attempt and
  // make a near-expiry POST fail precisely when the retry path was needed.
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();
  const token = await accessTokenFor(request);
  if (!token.accessToken) {
    const response = NextResponse.json({ detail: "Authentication required" }, { status: 401 });
    clearAuthCookies(response);
    return response;
  }

  let refreshed: TokenSet | undefined = token.refreshed;
  let upstream = await callApi(request, path, token.accessToken, body);
  if (upstream.status === 401 && !refreshed) {
    const refreshToken = tokenCookies(request).refreshToken;
    if (refreshToken) {
      try {
        refreshed = await refreshTokens(refreshToken);
        upstream = await callApi(request, path, refreshed.access_token, body);
      } catch {
        // The response below clears the unusable session.
      }
    }
  }

  const response = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders(upstream),
  });
  if (refreshed) setTokenCookies(response, refreshed);
  if (upstream.status === 401) clearAuthCookies(response);
  return response;
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
