# API Rules

> **Applies to:** the `api` service's public HTTP surface.
> **Related:** [conventions.md](./conventions.md) · [../context/architecture.md](../context/architecture.md) · [testing.md](./testing.md)

---

## 1. Versioning

- Base path: `/api/v1`. Every public route lives under it.
- **Breaking change ⇒ new version path.** Adding an optional field, adding an endpoint, or adding an enum value the client can ignore is not breaking. Removing a field, renaming one, changing a type, or tightening validation is.
- Two adjacent versions may run concurrently; older versions get a deprecation window announced via a `Deprecation` header and a `Sunset` date. *Proposed: only `/api/v1` exists, and no route sets these headers.*
- Internal service-to-service calls (`api` → `inference`) use their own `/v1` and are **not** part of the public contract.

## 2. Authentication & Authorization

### 2.1 Authentication

- `Authorization: Bearer <JWT>` on every route except `/health`, `/ready`, and the OpenAPI document and interactive docs.
- Tokens are OIDC-issued and verified against the provider's JWKS with caching and rotation support.
- Required claims: `sub`, `tenant_id`, `roles`, `groups`, `exp`, `iss`, `aud`. A token missing any of them is rejected with 401.

**The API has exactly one authentication mechanism, and cookies are not it.** The browser
authenticates to the *Next.js* server with an `HttpOnly` session cookie; that server holds
the token set and attaches the bearer header when it proxies to this API
([ADR-013](../context/architecture.md#adr-013--the-browser-never-holds-a-token)). No route
here reads a cookie, and none should be added — a cookie-authenticated API route is
ambient-authority and therefore CSRF-exposed, while a bearer header is not sent
automatically by the browser. The proxy is a client like any other.

Consequences worth stating, because they are easy to get wrong from the frontend side:

- Token refresh is the proxy's problem. This API returns 401 on an expired token and does
  not negotiate; the Next.js server rotates the refresh token and retries once.
- `DEV_AUTH_BYPASS=true` replaces the whole mechanism with the `X-Dev-User` header (or
  `Authorization: Bearer dev:<subject>`), which is trusted verbatim. It is a
  development-only path and both sides must opt in. The bypass also enables the
  unlisted `GET /api/v1/debug/users` helper; with the bypass off it returns 404.

### 2.2 The tenant rule

**`tenant_id` is read from the verified token and from nowhere else.**

Never from a path parameter, a query string, a request body, or a header. An endpoint that accepts a tenant identifier from the client is a cross-tenant vulnerability, and code review rejects it on sight. The tenant context dependency sets `app.current_tenant` for the request transaction; see [architecture.md § 4](../context/architecture.md#4-multi-tenancy--isolation).

### 2.3 Authorization

- Coarse-grained role checks happen in a route dependency (`require_role(...)`), exposed as the aliases `CuratorUser` (`admin`|`steward`) and `AclAdminUser` (`admin`). Role capabilities are tabulated in [architecture.md § 5.1](../context/architecture.md#51-subjects-and-resources).
- **Roles come from the `roles` table (`RoleAssignment` model) in Postgres, never from the token's `roles` claim.** The claim is still required for the token to be well-formed, but authorization reads the database so that `require_role` and the retrieval predicate cannot disagree about the same caller.
- Fine-grained document/collection permissions are **not** checked as a gate before retrieval — they are compiled into the retrieval predicate. See [architecture.md § 5.3](../context/architecture.md#53-resolution-to-a-retrieval-predicate).
- **A write endpoint checks both**: the role gate *and* an ACL permission check on the target resource. A curator role is not a grant on every collection.
- Endpoints that list resource *metadata* apply the same ACL predicate as `/search`. Titles and collection membership are not free — see the `read` column in [§ 12](#12-endpoint-inventory-planned-v1).
- A resource the caller cannot read returns **404, not 403**, when revealing existence would itself leak information. Use 403 only when the caller is known to be aware the resource exists.

**A role dependency must be attached to the route, not merely defined.** `require_role` existed unused for the whole first MVP pass, leaving every write endpoint — including ACL entry creation — open to any authenticated user (R-009). Review greps for the dependency and confirms a call site; the regression test asserts the *refused* request, not the permitted one.

## 3. Resource Conventions

- Nouns, plural, `kebab-case` where multi-word: `/documents`, `/acl/entries`, `/evals/runs`.
- Nesting at most one level deep: `/documents/{id}/versions` is fine; `/collections/{id}/documents/{id}/versions/{id}/chunks` is not — flatten with query filters.
- Path parameters are UUIDs. Slugs are accepted only for tenants, and only on admin routes.
- Verbs are HTTP methods, not path segments. The exception is a genuine action on a resource, such as `POST /documents/{id}/archive`, `/unarchive`, `/admin/documents/{id}/erase`, and `/admin/documents/{id}/legal-hold`.

| Method | Semantics |
| --- | --- |
| `GET` | Read. Safe, idempotent, cacheable. |
| `POST` | Create, or invoke an action. |
| `PATCH` | Partial update. The default for updates. |
| `PUT` | Full replacement. Rare — used only where the client genuinely owns the whole resource. |
| `DELETE` | Remove. The only implemented delete, `DELETE /acl/entries/{id}`, returns 204 on success and 404 when the entry does not exist. |

## 4. Requests & Responses

- `Content-Type: application/json` for everything except file upload (`multipart/form-data`) and SSE (`text/event-stream`).
- Field names are `snake_case` in JSON. The frontend maps to `camelCase` at its boundary using generated types.
- Timestamps are RFC 3339 with an explicit offset: `2026-07-25T14:32:11Z`.
- Money is a string decimal with an explicit currency field, never a float.
- Enums are lowercase strings. Clients must tolerate unknown values.
- Response envelopes: paginated collections return `{"data": [...], "next_cursor": "..."}`; single resources return the object directly, unwrapped. `POST /search` returns `{"data": [...], "strategy": ..., "acl_version": ...}` and is not paginated.

### 4.1 Pagination

Keyset, on `(created_at DESC, id DESC)`. Offset pagination is not used — it breaks under concurrent writes and performs badly on large tables. See [ADR-014](../context/architecture.md#adr-014--pagination-cursors-encode-a-position-not-an-offset).

| Parameter | Meaning |
| --- | --- |
| `limit` | Page size. Values above 200 are clamped to 200; values below 1 are rejected with `422 validation-failed`. The default is per endpoint — 200 on the admin and metadata listings, 50 on `GET /documents` |
| `cursor` | Opaque token from the previous response's `next_cursor` |

Rules:

- **The cursor is opaque.** It is base64url over a packed `(microseconds, uuid)` pair, and
  that layout is not a contract. Clients echo the token and never construct or parse one.
- **A malformed cursor is a `422 validation-failed`**, never an ignored parameter. Silently
  returning page one on a bad cursor looks to the caller like the collection ended.
- `next_cursor` is `null` on the last page, and only on the last page. It is derived by
  fetching `limit + 1` rows, so a full page is never reported as terminal.
- **There is no `sort` parameter.** The order is fixed per endpoint and backed by a
  matching composite index ([architecture.md § 14.6](../context/architecture.md#146-key-indexes)).
  Adding a sort option means adding an index and a cursor that names its ordering — not a
  new query parameter on its own.
- Tenant-scoped listings order within the tenant; document version and job listings
  order within their parent.

### 4.2 Filtering & sorting

- Filters are explicit named parameters, such as `?collection_id=…` on `GET /documents`. No generic query DSL in the URL. The generated OpenAPI schema lists each endpoint's filters.
- Ordering is fixed per endpoint; there is no supported `sort` parameter. See [pagination](#41-pagination) and the generated OpenAPI schema for supported query parameters.
- Full-text or semantic search is **not** a query parameter on a collection endpoint — it is `POST /search`, because it carries a body and is not cacheable.

## 5. Errors

RFC 7807 `application/problem+json` on every non-2xx response.

```json
{
  "type": "https://errors.enterprise-rag.dev/quota-exceeded",
  "title": "Quota exceeded",
  "status": 429,
  "detail": "Tenant daily budget exhausted",
  "instance": "/api/v1/chat/completions",
  "request_id": "01J8X...",
  "errors": []
}
```

- `type` is a **stable slug URI**. Clients branch on `type`, never on `detail` or `title` — those are human-facing and may change.
- `request_id` is always present and matches the `X-Request-Id` response header and the log correlation ID.
- `errors[]` carries per-field validation detail on 422: `[{"field": "limit", "message": "limit must be at least 1"}]`.
- **No stack traces, no SQL, no internal hostnames, no secret values** in any error field.

### 5.1 Status codes

| Code | Use |
| --- | --- |
| 200 | Success with a body |
| 201 | Resource created; the body is the created resource (no `Location` header is set) |
| 202 | Accepted for async processing; the body identifies the created resources and job (see [§ 8](#8-long-running-operations)) |
| 204 | Success, no body (deletes) |
| 401 | Missing, expired, or invalid token |
| 403 | Authenticated but not permitted, and existence is not secret |
| 404 | Not found, **or** not permitted where existence is secret |
| 409 | Conflict — duplicate content hash, concurrent version write |
| 413 | Upload exceeds the size limit |
| 415 | Unsupported media type |
| 405 | Method not offered, such as `DELETE /documents/{id}` |
| 422 | Invalid request body, query, or cursor; see `errors[]` |
| 429 | Rate limit (`Retry-After` set) or budget exceeded (no `Retry-After`) |
| 500 | Unhandled server error — always logged with the `request_id` |
| 502/503/504 | Upstream dependency failed, unavailable, or timed out; degraded modes are preferred over these |

### 5.2 Error type registry

| `type` slug | Status | Meaning |
| --- | --- | --- |
| `validation-failed` | 422 | Field-level validation errors in `errors[]` |
| `not-found` | 404 | Resource absent or invisible |
| `permission-denied` | 403 | Known resource, insufficient permission |
| `conflict` | 409 | Version or uniqueness conflict |
| `rate-limited` | 429 | Request rate exceeded |
| `quota-exceeded` | 429 | Tenant's rolling 24-hour budget exhausted |
| `upload-too-large` | 413 | File exceeds limit |
| `unsupported-media-type` | 415 | Parser has no handler for this MIME type |
| `retrieval-unavailable` | 503 | Postgres retrieval path failed |
| `generation-unavailable` | 503 | All generation tiers exhausted |
| `method-not-allowed` | 405 | Method not offered on the resource |
| `internal-error` | 500 | Unhandled |

## 6. Idempotency

- `GET`, `PUT`, `DELETE` are idempotent by definition.
- `POST /documents` and `POST /documents/{document_id}/versions` do not implement `Idempotency-Key` or response replay. Upload checks `content_sha256` against current versions of non-erased documents in the same tenant and collection. Matching bytes return `409 conflict`, including when a client retries an upload that was already accepted.
- After an ambiguous upload outcome, inspect the document listing and its [job history](#8-long-running-operations) before uploading again. A duplicate-content conflict does not return the original upload response or its job ID.
- `POST /chat/completions` is **not** idempotent and does not accept the header; a retry is a new query and a new cost ledger row.

## 7. Streaming

`POST /api/v1/chat/completions` responds with `text/event-stream` when `stream` is true, which is the default.

| Event | Payload | Notes |
| --- | --- | --- |
| `token` | `{"text": "..."}` | Verified answer text, chunked only after the groundedness gate passes |
| `citation` | `{"answer_sentence_idx": 3, "chunk_id": "...", "document_version_id": "...", "cited_text": "...", "start_char": 120, "end_char": 210, "document_title": "...", "staleness": "fresh", "is_suspect": false}` | Emitted as citations resolve |
| `status` | `{"stage": "retrieving" \| "generating" \| "verifying"}` | Drives progress UI before the verified answer is released |
| `usage` | `{"input_tokens": …, "output_tokens": …, "cache_read_input_tokens": …, "cost_usd": "0.0231", "model": "claude-opus-5"}` | Sent once, before `done` |
| `verdict` | `{"groundedness": "grounded" \| "partial" \| "unsupported", "citation_coverage": 0.94}` | Sent once, before `done` |
| `done` | `{"query_id": "..."}` | Terminal, success |
| `error` | `{"detail": "..."}` | Terminal, failure. Defined in the schema; the current chat service does not emit it (see rules) |

Rules:

- *Proposed:* a heartbeat comment (`: ping`) every 15 s to keep proxies from closing an idle stream. No heartbeat is sent today.
- Answer generation is buffer-then-verify by design. The server does not release model
  tokens before groundedness is known; doing so would expose an unsupported answer before
  the abstention gate could suppress it. The end-to-end verified-answer SLO in
  `product.md` is therefore normative, not time to first token.
- **Server-side accounting does not depend on the client.** The cost ledger row and the `queries` row are written even if the client disconnects mid-stream.
- Retrieval and budget failures are returned as problem responses before the stream opens. After the stream opens, a generation failure falls back to an extractive answer rather than an `error` event. Clients should still handle an `error` event, because HTTP 200 has already been sent by then.

## 8. Long-Running Operations

Document upload returns `202 Accepted` with `document_id`, `version_id`, `job_id`, and
`dispatch`. The `dispatch` value describes how ingestion was dispatched (`celery`,
`sync`, or `failed`); it is not the job's processing status.

Poll `GET /api/v1/documents/{document_id}/jobs` and locate the returned `job_id` in
`data[].id`. The authenticated caller must be able to read the document; an absent
or unreadable document returns 404. This is a paginated history across the
document's versions, using `limit` and `cursor` as described in [§ 4.1](#41-pagination).
Follow `next_cursor` if the job is not on the first page.

Each job includes `document_version_id`, `stage`, `status`, `attempts`, `error`,
`started_at`, `finished_at`, and `created_at`. See `JobPage` and `JobOut` in
[OpenAPI](../../openapi.json) for the exact schemas. There is no numeric `progress`
field on ingestion jobs.

Job states are `pending → running → succeeded | failed`. Inspect `error` when a
job fails. There is no ingestion cancellation or retry endpoint, and no
`/api/v1/ingestion-jobs/{id}` route. Upload acceptance does not prove ingestion
succeeded: check the terminal job state. Storage failure can return an HTTP error
after the document and failed job have already been persisted.

See [local ingestion troubleshooting](../guides/local-development.md#upload-stays-pending)
for worker diagnostics and recovery constraints.

## 9. Rate Limits & Quotas

**Implemented (Milestone A):** a fixed-window counter in Redis keyed by `scope:tenant_id:user_id`, applied per route group, plus a rolling 24-hour spend ceiling per tenant read from `cost_ledger`.

| Setting | Default | Applies to |
| --- | --- | --- |
| `CHAT_RATE_LIMIT_PER_MINUTE` | 10 | `POST /chat/completions` |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` | 20 | `POST /documents` and `POST /documents/{id}/versions` |
| `RATE_LIMIT_PER_MINUTE` | 60 | `POST /search` |
| `TENANT_DAILY_BUDGET_USD` | 25.0 | Checked before generation; 0 disables |

Chat is tightest because each call is a billable generation plus an embedding. Setting a limit to 0 disables it.

Two deliberate behaviours:

- **Rate limiting fails open.** If Redis is unreachable the request is allowed and a warning is logged; a cache outage must not become a full outage. The cached client is dropped on failure so the next request rebuilds it rather than staying permanently broken on a dead event loop.
- **The budget guard fails closed and does not depend on Redis.** It reads `cost_ledger` in Postgres, so cost protection survives a cache outage even though request-rate protection does not.

The budget check runs *before* the SSE stream opens, so an over-budget tenant receives a 429 rather than a 200 whose body turns out to be an error event.

Rate-limited routes carry these headers on success and on `429 rate-limited`:

| Header | Meaning |
| --- | --- |
| `RateLimit-Limit` | Window capacity |
| `RateLimit-Remaining` | Requests left in the current window |
| `RateLimit-Reset` | Unix timestamp (seconds) at which the current window ends |

- `429 rate-limited` responses carry `Retry-After`. `429 quota-exceeded` does not.
- These headers are set by the rate-limit dependency. An endpoint that returns a `Response` object directly — `/chat/completions` returns a `StreamingResponse` — must copy them onto that response explicitly, because the framework only merges dependency-set headers into responses it builds from a return value.
- **Planned (not yet implemented):** token-bucket semantics and independent tenant-level buckets.
- Budget exhaustion is a distinct error type (`quota-exceeded`) from rate limiting (`rate-limited`), because the client remediation differs: one is "wait", the other is "contact your admin".

## 10. Caching

- *Proposed:* `GET` responses for slow-changing resources carry `ETag` and support `If-None-Match` → 304. No route implements this today.
- `Cache-Control: no-store, private` is set on every API response. Nothing tenant-scoped is ever cached in a shared proxy.
- Search and chat responses are never HTTP-cached. Any answer caching is server-side, per-(user, query, acl_version), and is out of v1 scope.

## 11. OpenAPI

- Generated from Pydantic models by FastAPI. Hand-written schema files are not permitted.
- `openapi.json` and `apps/web/openapi.json` are committed. CI compares both against a schema generated from the current FastAPI application.
- Frontend TypeScript types are generated from the committed schema. Generated types are also committed, so drift is a diff.
- Include summaries, descriptions, and examples when adding endpoints; existing coverage is incomplete.

The canonical machine-readable reference is [openapi.json](../../openapi.json).
A running API serves it at `/api/openapi.json` and provides interactive docs at
`/api/docs`. Follow the [generation workflow](conventions.md#2-toolchain) after
changing routes or models.

## 12. Endpoint Inventory (planned v1)

This section combines implemented routes and proposed interfaces. A row is
implemented only when it is marked **Implemented**; every other row is proposed.
Phase numbers refer to [roadmap.md](../context/roadmap.md), not implementation status. Use
[generated OpenAPI](../../openapi.json) to determine whether a route exists and
which parameters it accepts. The upload and polling workflow in [§ 8](#8-long-running-operations)
describes the implemented interface.

**Role column** names the minimum role required by the route dependency, where one is implemented today. `—` means any authenticated caller, still scoped by RLS and (where marked) the ACL predicate. A role is necessary but never sufficient on writes: see [§ 2.3](#23-authorization).

### Health & meta

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/health` | **Implemented.** Liveness — process is up | 0 |
| `GET` | `/ready` | Readiness. **Implemented.** Probes Postgres, Redis, **and the inference service** and returns **503 + `{"status":"degraded"}`** when any is unreachable, with a per-dependency `checks` object. Inference is a hard dependency of `/search` and `/chat/completions`, so a probe that ignored it reported `ready` while both primary endpoints were dead. `/health` is liveness only and never touches a dependency. The inference service exposes its own `/health` and `/ready`, unauthenticated, so the API and the Compose healthcheck can reach them. | 0 |
| `GET` | `/metrics` | Prometheus scrape | 5 |
| `GET` | `/api/openapi.json` | **Implemented.** Schema; interactive docs at `/api/docs` | 0 |

### Identity

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/me` | **Implemented.** Current user, roles, groups, tenant | 0 |

### Tenants (platform admin)

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/tenants` | List | 0 |
| `POST` | `/api/v1/tenants` | Provision | 0 |
| `GET` | `/api/v1/tenants/{id}` | Detail | 0 |
| `PATCH` | `/api/v1/tenants/{id}` | Settings, quotas, budget | 5 |

### Users, groups, roles

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/users` | List within tenant | 0 |
| `GET` | `/api/v1/groups` · `POST` · `PATCH` · `DELETE /{id}` | Group CRUD | 2 |
| `POST` | `/api/v1/groups/{id}/members` · `DELETE /{id}/members/{user_id}` | Membership | 2 |
| `PUT` | `/api/v1/users/{id}/roles` | Assign roles | 2 |

### Collections

| Method | Path | Purpose | Role | Phase |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/collections` | **Implemented.** List collections in the tenant | — | 1 |
| `GET` | `/api/v1/collections/{id}` | **Implemented.** Collection detail | — | 1 |
| `POST` | `/api/v1/collections` | **Implemented.** Create | `steward` | 1 |
| `PATCH` · `DELETE` | `/api/v1/collections/{id}` | Update / remove | `steward` | 1 |
| `GET` | `/api/v1/collections/{id}/acl` · `PUT` | Read / replace ACL entries | `admin` | 2 |
| `POST` | `/api/v1/acl/entries` · `GET` | **Implemented.** Create (201) / list ACL grants. **Admin only** — a self-grant here widens the caller's own retrieval predicate. | `admin` | 2 |
| `DELETE` | `/api/v1/acl/entries/{id}` | **Implemented.** Revoke a grant; 204, or 404 when absent | `admin` | 2 |

### Documents

| Method | Path | Purpose | Role | Phase |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/documents` | **Implemented.** Upload (multipart) → 202 with `document_id`, `version_id`, `job_id`, `dispatch`. Also requires ACL `write` on the target collection; 413 past `MAX_UPLOAD_BYTES`, 415 outside the PDF/MD/TXT allowlist. The allowlist is decided by **file content** (PDF magic bytes, text sniffing), not the client's `Content-Type`. Processing failures after successful storage can still return 202; inspect job history. A storage failure can return an HTTP error after a failed job is persisted. | `steward` | 1 |
| `GET` | `/api/v1/documents` | **Implemented.** List, filterable by `collection_id`. **ACL-filtered.** | — | 1 |
| `GET` | `/api/v1/documents/{id}` | **Implemented.** Detail incl. current version. **ACL-filtered** (404 when not readable). | — | 1 |
| `PATCH` | `/api/v1/documents/{id}` | Metadata, owner, review interval | `steward` | 1 |
| `POST` | `/api/v1/documents/{id}/archive` | **Implemented.** Tombstone. Excluded from new retrieval; versions, chunks, and citation targets preserved. Reversible. Requires ACL **`write`** on the document's collection, not merely `read` — archiving removes a document from every user's retrieval, which is a write-level effect. | `steward` | 1 |
| `POST` | `/api/v1/documents/{id}/unarchive` | **Implemented.** Restore an archived document to retrieval. Requires ACL **`write`** on the collection. | `steward` | 1 |
| `DELETE` | `/api/v1/documents/{id}` | **Implemented as a refusal.** Always returns 405 with a problem body pointing at `/archive` and `/erase` — see [architecture.md § 6.4](../context/architecture.md#64-removal-archival-not-deletion) | — | 1 |
| `POST` | `/api/v1/documents/{id}/versions` | **Implemented.** Upload replacement bytes as version `n+1` (multipart, same fields as `POST /documents`). In one transaction the current version gets `effective_to = now()`, the new row is inserted with `supersedes_id` pointing at it, and ingest is enqueued. Requires ACL `write` on the document's collection. 409 when the bytes match the current version of a non-erased document in that collection. Equivalently, `POST /api/v1/documents` accepts a `document_id` form field. | `steward` | 1 |
| `GET` | `/api/v1/documents/{id}/versions` | **Implemented.** Version history / supersession chain, newest first. **ACL-filtered** (404 when the document is not readable). | — | 1 |
| `GET` | `/api/v1/documents/{id}/versions/{vid}/content` | Signed URL to original bytes | — | 1 |
| `GET` | `/api/v1/documents/{id}/jobs` | **Implemented.** Ingestion job history for the document. **ACL-filtered.** | — | 1 |
| `POST` | `/api/v1/documents/{id}/reindex` | Force re-chunk + re-embed | `steward` | 1 |
| `GET` | `/api/v1/documents/{id}/acl` · `PUT` | Document-level ACL overrides | `admin` | 2 |
| `POST` | `/api/v1/documents/{id}/review` | Mark reviewed; resets staleness | `steward` | 5 |

### Ingestion jobs

**Planned only:** none of the three routes below is implemented. Current clients
use `GET /api/v1/documents/{document_id}/jobs`; see [§ 8](#8-long-running-operations).

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/ingestion-jobs` | List, filterable by status | 1 |
| `GET` | `/api/v1/ingestion-jobs/{id}` | Status, stage, progress, error | 1 |
| `POST` | `/api/v1/ingestion-jobs/{id}/retry` | Re-run a failed job | 1 |

### Search & chat

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `POST` | `/api/v1/search` | **Implemented.** Retrieval only. Body: `query`, `strategy?`, `top_k?` (1–50), `as_of?`. Unknown fields are ignored; there is no collection filter. Returns ranked chunks with scores and provenance. | 2 |
| `POST` | `/api/v1/chat/completions` | **Implemented.** Cited answer. SSE when `stream` is true (default). Retrieval is resolved **before** the response starts, so an unavailable inference service produces a normal `503 retrieval-unavailable` problem response rather than a 200 whose stream stops after the first event. Rate-limit headers are copied onto the streaming response. Degraded (no-key) behavior is governed by [architecture § ADR-012](../context/architecture.md#adr-012--degraded-mode-evidence-is-lexical-or-it-does-not-exist). Request body below. | 3 |
| `GET` | `/api/v1/queries/{id}` | **Implemented.** Audit record: question, answer, verdict, citation coverage, retrieved chunk ids, citations. Readable by the user who asked it or by a tenant `admin`; **404** (not 403) for anyone else, so a caller who may not read a query does not learn it exists. `retrieved_chunk_ids` records both the ranked hits and any chunk actually emitted as a source, so every citation resolves against it. | 3 |
| `POST` | `/api/v1/queries/{id}/feedback` | Rating + reason code + comment | 6 |
| `POST` | `/api/v1/feedback` | **Implemented.** Rate an answer. Restricted to the user who made the query (404 otherwise) — an answer only its asker saw is not rateable by other tenant members. One vote per (query, user), enforced by a partial unique index; re-submitting **updates** the vote and returns 200 rather than 201. | 3 |

#### `POST /chat/completions` — request body

`question` and `messages` are alternatives; exactly one must be present.

| Field | Type | Notes |
| --- | --- | --- |
| `question` | `string`, 1–8000 | Single-turn form. Retained; not deprecated |
| `messages` | `[{role, content}]`, 1–12 | Multi-turn form. Roles must alternate, first and last must be `user` |
| `stream` | `bool`, default `true` | SSE when true |
| `strategy`, `as_of` | | As on `/search`. Chat has no `top_k` or collection filter |

Validation failure is a `422 validation-failed`, not a silent repair:

- Sending neither `question` nor `messages` is an error. So is a `messages` list that ends
  on an `assistant` turn — the API answers a question, and the last turn *is* the question.
- Each user message is capped at 8000 characters and the whole conversation at 64000.
  These are enforced on the request, before retrieval or any model call, so a client cannot
  spend tenant budget by sending an oversized history.
- Only the **last six** prior messages (three user/assistant exchanges) are forwarded to the model, and prior turns are
  forwarded as text only. The reasoning — citation indices and per-request ACL resolution
  — is in [architecture § 8.2](../context/architecture.md#82-request-shape).

The server holds no conversation state. History is client-supplied on every request, which
also means it is re-validated on every request and never trusted from an earlier one.

### Evaluation

Every evaluation route requires the `admin` role and is scoped to the caller's tenant.

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/evals/datasets` · `POST` | **Implemented.** Dataset registry | 4 |
| `GET` | `/api/v1/evals/datasets/{id}/items` | **Implemented.** Golden items, paginated | 4 |
| `POST` | `/api/v1/evals/runs` | **Implemented.** Trigger a run (202) | 4 |
| `GET` | `/api/v1/evals/runs` | List runs | 4 |
| `GET` | `/api/v1/evals/runs/{id}` | **Implemented.** Run detail with aggregate metrics | 4 |
| `GET` | `/api/v1/evals/runs/{id}/results` | **Implemented.** Per-item results, paginated | 4 |
| `GET` | `/api/v1/evals/runs/compare?ids=a,b,c` | **Implemented.** Canonical comparison matrix; IDs are ordered and the first run is the baseline. Every run must be complete with exactly one result per dataset item; conflicts use RFC 7807. A malformed `ids` value also returns `409 conflict`. | 4 |

### Cost & quotas (admin)

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `POST` | `/api/v1/admin/documents/{id}/erase` | **Implemented.** **Privileged, irreversible.** `admin` only. Body: `{reason, legal_basis}`. Deletes chunks and embeddings (cascading to the citations that pointed at them), sets `erased_at`, and writes an `erasure_log` row with the affected counts. Object bytes are deleted after the DB commit — a storage failure is logged, never rolled back over an erasure the audit log already records. 409 under `legal_hold` or if already erased. | 1 |
| `POST` | `/api/v1/admin/documents/{id}/legal-hold` | **Implemented.** `admin` only. Body: `{legal_hold: bool}`. Places or lifts the hold that blocks erasure. | 1 |
| `GET` | `/api/v1/admin/erasures` | **Implemented.** Erasure audit log for the tenant, newest first: document, actor, reason, legal basis, versions and citations affected. `admin` only. | 1 |
| `GET` | `/api/v1/admin/costs` | Aggregated spend by tenant / model / purpose / period | 5 |
| `GET` | `/api/v1/admin/quotas` · `PUT` | Rate limits and budgets | 5 |
| `GET` | `/api/v1/admin/usage` | Query volume, latency percentiles, verdict distribution | 5 |

### Freshness

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/freshness/queue` | Documents needing review, ranked by staleness | 5 |
| `GET` | `/api/v1/freshness/conflicts` | Detected contradictory current versions | 5 |

## 13. Security Requirements

| Control | Requirement | Status |
| --- | --- | --- |
| TLS | Required in every environment except `local` | Deployment concern; no deployment is implemented |
| CORS | Explicit origin allowlist (`CORS_ALLOW_ORIGINS`). `*` is never permitted with credentials. | Implemented |
| Headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, and a CSP on the web app | Implemented (API and web middleware) |
| Upload limits | MIME sniffing on content, not on the filename extension; size capped by `MAX_UPLOAD_BYTES` (default 25 MiB) | Implemented. A page limit is proposed |
| Document content delivery | **Proxied by default** — `GET /documents/{id}/versions/{vid}/content` streams through the authenticated API, so every access is ACL-checked at request time and lands in the audit log. See the note below before enabling the presigned alternative. | Proposed: no content route exists |
| Request size | 10 MB JSON body limit | Proposed |
| Timeouts | Per [architecture.md § 13.1](../context/architecture.md#131-timeouts) | Partial |
| Egress scan | Answers pass a secret/PII pattern check before leaving the API | Proposed |
| Audit | Every mutating admin action is logged with actor, target, and before/after | Partial: erasures write `erasure_log` |

### 13.1 Presigned URLs are bearer credentials

An S3 presigned URL **cannot be scoped to a user**. It is a bearer credential: whoever holds the string can fetch the object until it expires, with no further authentication and no way to distinguish the original requester from anyone the link was forwarded to. Any documentation claiming otherwise is wrong, and this section exists because an earlier draft of this file made exactly that claim.

Two delivery modes, with the trade stated plainly:

| Mode | Access control | Audit | Cost |
| --- | --- | --- | --- |
| **Proxy through the API** *(default)* | Re-checked on every byte range requested | Every access logged | API bandwidth and a streaming handler |
| **Presigned URL** *(opt-in)* | None after issuance — object-scoped, time-limited, bearer | Issuance is logged; the fetch itself is not | Offloads bandwidth to S3 |

If the presigned mode is enabled, these consequences are accepted explicitly and must appear in the tenant's security documentation:

- **A URL issued before an ACL revocation stays usable until it expires** (≤ 15 minutes). Revocation is not retroactive over already-issued links.
- A forwarded or logged URL is a working credential for its remaining lifetime.
- Downloads do not appear in the access audit trail.

Because the audit requirement in [product.md § 9](../context/product.md#9-non-functional-requirements) says every access must be reconstructable, the proxy is the default and presigning is a per-tenant opt-in for bandwidth-sensitive deployments — never the other way round.
