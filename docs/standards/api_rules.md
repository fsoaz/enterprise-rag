# API Rules

> **Applies to:** the `api` service's public HTTP surface.
> **Related:** [conventions.md](./conventions.md) · [../context/architecture.md](../context/architecture.md) · [testing.md](./testing.md)

---

## 1. Versioning

- Base path: `/api/v1`. Every public route lives under it.
- **Breaking change ⇒ new version path.** Adding an optional field, adding an endpoint, or adding an enum value the client can ignore is not breaking. Removing a field, renaming one, changing a type, or tightening validation is.
- Two adjacent versions may run concurrently; older versions get a deprecation window announced via a `Deprecation` header and a `Sunset` date.
- Internal service-to-service calls (`api` → `inference`) use their own `/v1` and are **not** part of the public contract.

## 2. Authentication & Authorization

### 2.1 Authentication

- `Authorization: Bearer <JWT>` on every route except `/health`, `/ready`, `/metrics`, and the OpenAPI document.
- Tokens are OIDC-issued and verified against the provider's JWKS with caching and rotation support.
- Required claims: `sub`, `tenant_id`, `roles[]`, `groups[]`, `exp`, `iss`, `aud`. A token missing any of them is rejected with 401.

### 2.2 The tenant rule

**`tenant_id` is read from the verified token and from nowhere else.**

Never from a path parameter, a query string, a request body, or a header. An endpoint that accepts a tenant identifier from the client is a cross-tenant vulnerability, and code review rejects it on sight. The tenant context dependency sets `app.current_tenant` for the request transaction; see [architecture.md § 4](../context/architecture.md#4-multi-tenancy--isolation).

### 2.3 Authorization

- Coarse-grained role checks happen in a route dependency (`require_role(...)`), exposed as the aliases `CuratorUser` (`admin`|`steward`) and `AclAdminUser` (`admin`). Role capabilities are tabulated in [architecture.md § 5.1](../context/architecture.md#51-subjects-and-resources).
- **Roles come from `role_assignments` in Postgres, never from the token's `roles[]` claim.** The claim is still required for the token to be well-formed, but authorization reads the database so that `require_role` and the retrieval predicate cannot disagree about the same caller.
- Fine-grained document/collection permissions are **not** checked as a gate before retrieval — they are compiled into the retrieval predicate. See [architecture.md § 5.3](../context/architecture.md#53-resolution-to-a-retrieval-predicate).
- **A write endpoint checks both**: the role gate *and* an ACL permission check on the target resource. A curator role is not a grant on every collection.
- Endpoints that list resource *metadata* apply the same ACL predicate as `/search`. Titles and collection membership are not free — see the `read` column in [§ 12](#12-endpoint-inventory-planned-v1).
- A resource the caller cannot read returns **404, not 403**, when revealing existence would itself leak information. Use 403 only when the caller is known to be aware the resource exists.

**A role dependency must be attached to the route, not merely defined.** `require_role` existed unused for the whole first MVP pass, leaving every write endpoint — including ACL entry creation — open to any authenticated user (R-009). Review greps for the dependency and confirms a call site; the regression test asserts the *refused* request, not the permitted one.

## 3. Resource Conventions

- Nouns, plural, `kebab-case` where multi-word: `/documents`, `/document-versions`, `/eval-runs`.
- Nesting at most one level deep: `/documents/{id}/versions` is fine; `/collections/{id}/documents/{id}/versions/{id}/chunks` is not — flatten with query filters.
- Path parameters are UUIDs. Slugs are accepted only for tenants, and only on admin routes.
- Verbs are HTTP methods, not path segments. The single exception is a genuine action on a resource: `POST /documents/{id}/reindex`.

| Method | Semantics |
| --- | --- |
| `GET` | Read. Safe, idempotent, cacheable. |
| `POST` | Create, or invoke an action. |
| `PATCH` | Partial update. The default for updates. |
| `PUT` | Full replacement. Rare — used only where the client genuinely owns the whole resource. |
| `DELETE` | Remove. Idempotent: deleting an already-deleted resource returns 204. |

## 4. Requests & Responses

- `Content-Type: application/json` for everything except file upload (`multipart/form-data`) and SSE (`text/event-stream`).
- Field names are `snake_case` in JSON. The frontend maps to `camelCase` at its boundary using generated types.
- Timestamps are RFC 3339 with an explicit offset: `2026-07-25T14:32:11Z`.
- Money is a string decimal with an explicit currency field, never a float.
- Enums are lowercase strings. Clients must tolerate unknown values.
- Response envelopes: collections return `{"data": [...], "next_cursor": "..."}`; single resources return the object directly, unwrapped.

### 4.1 Pagination

Cursor-based. Offset pagination is not used — it breaks under concurrent writes and performs badly on large tables.

| Parameter | Meaning |
| --- | --- |
| `limit` | Page size, default 50, max 200 |
| `cursor` | Opaque token from the previous response's `next_cursor` |

`next_cursor` is `null` on the last page. Cursors encode the sort order; reusing a cursor with a different `sort` returns 400.

### 4.2 Filtering & sorting

- Filters are explicit named parameters: `?collection_id=…&language=pt&status=active`. No generic query DSL in the URL.
- Sorting: `?sort=created_at` / `?sort=-created_at` for descending. Allowed sort fields are enumerated per endpoint in the OpenAPI schema.
- Full-text or semantic search is **not** a query parameter on a collection endpoint — it is `POST /search`, because it carries a body and is not cacheable.

## 5. Errors

RFC 7807 `application/problem+json` on every non-2xx response.

```json
{
  "type": "https://errors.enterprise-rag.dev/quota-exceeded",
  "title": "Monthly budget exhausted",
  "status": 429,
  "detail": "Tenant has consumed 100% of its USD budget for 2026-07.",
  "instance": "/api/v1/chat/completions",
  "request_id": "01J8X...",
  "errors": []
}
```

- `type` is a **stable slug URI**. Clients branch on `type`, never on `detail` or `title` — those are human-facing and may change.
- `request_id` is always present and matches the `X-Request-Id` response header and the log correlation ID.
- `errors[]` carries per-field validation detail on 422: `[{"field": "limit", "message": "must be ≤ 200"}]`.
- **No stack traces, no SQL, no internal hostnames, no secret values** in any error field.

### 5.1 Status codes

| Code | Use |
| --- | --- |
| 200 | Success with a body |
| 201 | Resource created; `Location` header set |
| 202 | Accepted for async processing; body carries the job resource |
| 204 | Success, no body (deletes) |
| 400 | Malformed request |
| 401 | Missing, expired, or invalid token |
| 403 | Authenticated but not permitted, and existence is not secret |
| 404 | Not found, **or** not permitted where existence is secret |
| 409 | Conflict — duplicate content hash, concurrent version write |
| 413 | Upload exceeds the size limit |
| 415 | Unsupported media type |
| 422 | Semantically invalid; see `errors[]` |
| 429 | Rate limit or budget exceeded; `Retry-After` set |
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
| `quota-exceeded` | 429 | Monthly budget exhausted |
| `upload-too-large` | 413 | File exceeds limit |
| `unsupported-media-type` | 415 | Parser has no handler for this MIME type |
| `retrieval-unavailable` | 503 | Postgres retrieval path failed |
| `generation-unavailable` | 503 | All generation tiers exhausted |
| `internal-error` | 500 | Unhandled |

## 6. Idempotency

- `GET`, `PUT`, `DELETE` are idempotent by definition.
- `POST /documents` (upload) accepts an `Idempotency-Key` header. A repeated key within 24 hours returns the original response rather than creating a duplicate. Independently, identical file bytes are deduplicated by `content_sha256` — the key protects against client retries, the hash protects against re-upload.
- `POST /chat/completions` is **not** idempotent and does not accept the header; a retry is a new query and a new cost ledger row.

## 7. Streaming

`POST /api/v1/chat/completions` responds with `text/event-stream` when `stream: true`.

| Event | Payload | Notes |
| --- | --- | --- |
| `token` | `{"text": "..."}` | Incremental answer text |
| `citation` | `{"answer_sentence_idx": 3, "chunk_id": "...", "document_version_id": "...", "cited_text": "...", "start_char": 120, "end_char": 210, "document_title": "...", "staleness": "fresh"}` | Emitted as citations resolve |
| `status` | `{"stage": "retrieving" \| "reranking" \| "generating"}` | Drives progress UI before the first token |
| `usage` | `{"input_tokens": …, "output_tokens": …, "cache_read_input_tokens": …, "cost_usd": "0.0231", "model": "claude-opus-5"}` | Sent once, before `done` |
| `verdict` | `{"groundedness": "grounded" \| "partial" \| "unsupported", "citation_coverage": 0.94}` | Sent once, before `done` |
| `done` | `{"query_id": "..."}` | Terminal, success |
| `error` | RFC 7807 body | Terminal, failure |

Rules:

- A heartbeat comment (`: ping`) every 15 s keeps proxies from closing an idle stream.
- **Server-side accounting does not depend on the client.** The cost ledger row and the `queries` row are written even if the client disconnects mid-stream.
- An error after the stream has opened is delivered as an `error` event with HTTP 200 already sent — clients must handle failure on the event channel, not only on the status code.

## 8. Long-Running Operations

Anything that cannot reliably finish inside the request budget returns `202 Accepted` plus a job resource.

```http
POST /api/v1/documents            → 202  { "job_id": "...", "document_id": "...", "status": "queued" }
GET  /api/v1/ingestion-jobs/{id}  → 200  { "status": "running", "stage": "embed", "progress": 0.6, ... }
```

Job states: `queued → running → succeeded | failed | cancelled`. A `failed` job carries a readable `error` field. Clients poll; there is no long-poll variant.

## 9. Rate Limits & Quotas

- Token bucket in Redis, keyed by `tenant_id` and by `user_id` independently. The stricter limit wins.
- Every response carries:

| Header | Meaning |
| --- | --- |
| `RateLimit-Limit` | Window capacity |
| `RateLimit-Remaining` | Tokens left |
| `RateLimit-Reset` | Seconds until refill |

- 429 responses always carry `Retry-After`.
- Budget exhaustion is a distinct error type (`quota-exceeded`) from rate limiting (`rate-limited`), because the client remediation differs: one is "wait", the other is "contact your admin".

## 10. Caching

- `GET` responses for slow-changing resources carry `ETag` and support `If-None-Match` → 304.
- `Cache-Control: private, no-store` on anything containing document content or answers. Nothing tenant-scoped is ever cached in a shared proxy.
- Search and chat responses are never HTTP-cached. Any answer caching is server-side, per-(user, query, acl_version), and is out of v1 scope.

## 11. OpenAPI

- Generated from Pydantic models by FastAPI. Hand-written schema files are not permitted.
- `openapi.json` is **committed** and diffed in CI. An uncommitted schema change fails the build — this is what makes a breaking change visible in review.
- Frontend TypeScript types are generated from the committed schema. Generated types are also committed, so drift is a diff.
- Every endpoint has a summary, a description, an example request, and an example response.

## 12. Endpoint Inventory (planned v1)

Phase column refers to [roadmap.md](../context/roadmap.md).

**Role column** names the minimum role required by the route dependency, where one is implemented today. `—` means any authenticated caller, still scoped by RLS and (where marked) the ACL predicate. A role is necessary but never sufficient on writes: see [§ 2.3](#23-authorization).

### Health & meta

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness — process is up | 0 |
| `GET` | `/ready` | Readiness — dependencies reachable | 0 |
| `GET` | `/metrics` | Prometheus scrape | 5 |
| `GET` | `/api/v1/openapi.json` | Schema | 0 |

### Identity

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/me` | Current user, roles, groups, tenant | 0 |

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
| `GET` | `/api/v1/collections` | List collections in the tenant | — | 1 |
| `POST` | `/api/v1/collections` · `PATCH /{id}` · `DELETE /{id}` | Create / update / remove | `steward` | 1 |
| `GET` | `/api/v1/collections/{id}/acl` · `PUT` | Read / replace ACL entries | `admin` | 2 |
| `POST` | `/api/v1/acl/entries` · `GET` | Create / list ACL grants. **Admin only** — a self-grant here widens the caller's own retrieval predicate. | `admin` | 2 |

### Documents

| Method | Path | Purpose | Role | Phase |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/documents` | Upload (multipart) → 202 + job. Also requires ACL `write` on the target collection; 413 past `MAX_UPLOAD_BYTES`, 415 outside the PDF/MD/TXT allowlist. | `steward` | 1 |
| `GET` | `/api/v1/documents` | List, filterable by collection/status/language/staleness. **ACL-filtered.** | — | 1 |
| `GET` | `/api/v1/documents/{id}` | Detail incl. current version. **ACL-filtered** (404 when not readable). | — | 1 |
| `PATCH` | `/api/v1/documents/{id}` | Metadata, owner, review interval | `steward` | 1 |
| `POST` | `/api/v1/documents/{id}/archive` | Tombstone. Excluded from new retrieval; versions, chunks, and citation targets preserved. Reversible. **ACL-filtered.** | `steward` | 1 |
| `POST` | `/api/v1/documents/{id}/unarchive` | Restore an archived document to retrieval. **ACL-filtered.** | `steward` | 1 |
| `DELETE` | `/api/v1/documents/{id}` | **Not offered.** Returns 405 with a problem body pointing at `/archive` and `/erase` — see [architecture.md § 6.4](../context/architecture.md#64-removal-archival-not-deletion) | — | 1 |
| `GET` | `/api/v1/documents/{id}/versions` | Version history / supersession chain | — | 1 |
| `GET` | `/api/v1/documents/{id}/versions/{vid}/content` | Signed URL to original bytes | — | 1 |
| `GET` | `/api/v1/documents/{id}/jobs` | Ingestion job history for the document. **ACL-filtered.** | — | 1 |
| `POST` | `/api/v1/documents/{id}/reindex` | Force re-chunk + re-embed | `steward` | 1 |
| `GET` | `/api/v1/documents/{id}/acl` · `PUT` | Document-level ACL overrides | `admin` | 2 |
| `POST` | `/api/v1/documents/{id}/review` | Mark reviewed; resets staleness | `steward` | 5 |

### Ingestion jobs

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/ingestion-jobs` | List, filterable by status | 1 |
| `GET` | `/api/v1/ingestion-jobs/{id}` | Status, stage, progress, error | 1 |
| `POST` | `/api/v1/ingestion-jobs/{id}/retry` | Re-run a failed job | 1 |

### Search & chat

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `POST` | `/api/v1/search` | Retrieval only. Body: `query`, `strategy?`, `top_k?`, `as_of?`, `collection_ids?`. Returns ranked chunks with scores and provenance. | 2 |
| `POST` | `/api/v1/chat/completions` | Cited answer. SSE when `stream: true`. Body adds `messages`, `stream`. | 3 |
| `GET` | `/api/v1/queries/{id}` | Audit record: question, retrieved chunks, citations, verdict, cost | 3 |
| `POST` | `/api/v1/queries/{id}/feedback` | Rating + reason code + comment | 6 |

### Evaluation

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/eval-datasets` · `POST` | Dataset registry | 4 |
| `GET` | `/api/v1/eval-datasets/{id}/items` | Golden items | 4 |
| `GET` | `/api/v1/eval-runs` · `POST` | List / trigger a run | 4 |
| `GET` | `/api/v1/eval-runs/{id}` | Run detail with aggregate metrics | 4 |
| `GET` | `/api/v1/eval-runs/{id}/results` | Per-item results, paginated | 4 |
| `GET` | `/api/v1/eval-runs/compare?ids=a,b,c` | Strategy comparison matrix | 4 |

### Cost & quotas (admin)

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `POST` | `/api/v1/admin/documents/{id}/erase` | **Privileged, irreversible.** Legal/privacy erasure: purges bytes, chunk text, and embeddings; retains tombstones, nulled citations, and an `erasure_log` entry. Refused with 409 under `legal_hold`. | 1 |
| `GET` | `/api/v1/admin/erasures` | Erasure audit log | 1 |
| `GET` | `/api/v1/admin/costs` | Aggregated spend by tenant / model / purpose / period | 5 |
| `GET` | `/api/v1/admin/quotas` · `PUT` | Rate limits and monthly budgets | 5 |
| `GET` | `/api/v1/admin/usage` | Query volume, latency percentiles, verdict distribution | 5 |

### Freshness

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/v1/freshness/queue` | Documents needing review, ranked by staleness | 5 |
| `GET` | `/api/v1/freshness/conflicts` | Detected contradictory current versions | 5 |

## 13. Security Requirements

| Control | Requirement |
| --- | --- |
| TLS | Required in every environment except `local` |
| CORS | Explicit origin allowlist. `*` is never permitted with credentials. |
| Headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, and a CSP on the web app |
| Upload limits | 100 MB per file, 500 pages per document, MIME sniffing on content and not on the filename extension |
| Document content delivery | **Proxied by default** — `GET /documents/{id}/versions/{vid}/content` streams through the authenticated API, so every access is ACL-checked at request time and lands in the audit log. See the note below before enabling the presigned alternative. |
| Request size | 10 MB JSON body limit |
| Timeouts | Per [architecture.md § 13.1](../context/architecture.md#131-timeouts) |
| Egress scan | Answers pass a secret/PII pattern check before leaving the API |
| Audit | Every mutating admin action is logged with actor, target, and before/after |

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
