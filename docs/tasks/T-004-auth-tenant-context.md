# T-004 — OIDC auth and tenant context

| Field | Value |
| --- | --- |
| **ID** | `T-004` |
| **Phase** | `0` |
| **Status** | `done` |
| **Branch** | `feat/T-004-auth-tenant-context` |
| **Size** | `M` |
| **Depends on** | `T-003` |
| **Blocks** | `T-006`, Phase 1 APIs |

---

## Goal

Every authenticated API request carries a verified identity and a transaction-local `app.current_tenant` GUC so RLS is the tenancy backstop — and `tenant_id` is never taken from the client.

## Context

- Design: [architecture.md § 4](../context/architecture.md#4-multi-tenancy--isolation)
- API: [api_rules.md § 2](../standards/api_rules.md#2-authentication--authorization)
- Stories satisfied: PA-1
- Prior findings: none

## Acceptance Criteria

- [x] Settings load `DATABASE_URL`, `OIDC_*`, `DEV_AUTH_BYPASS` from env
- [x] JWT verified against JWKS when `DEV_AUTH_BYPASS=false`
- [x] Dev bypass accepts `X-Dev-User` and `Bearer dev:<external_subject>`, resolves user from DB
- [x] `get_db_session` sets `SET LOCAL app.current_tenant` from the auth user only
- [x] `DomainError` → RFC 7807 `problem+json` with `request_id` / `X-Request-Id`
- [x] `GET /api/v1/me` returns tenant_id and roles
- [x] Acme admin cannot see Globex users (debug endpoint + session query)
- [x] Missing auth → 401 on protected routes
- [x] `.env.example` documents `DEV_AUTH_BYPASS=true`

## Out of Scope

- Keycloak realm export / token minting helpers
- Full users/groups CRUD API
- Frontend OIDC login

## Design Notes

- Identity bootstrap (external_subject → user) uses `DATABASE_URL_MIGRATE` (BYPASSRLS) because `users` is RLS-protected and no tenant GUC exists yet.
- Request DB sessions use `rag_app` + `SET LOCAL app.current_tenant`.
- `DEV_AUTH_BYPASS` is for local/CI only; production must leave it false.

## Files Expected to Change

| Path | Change |
| --- | --- |
| `apps/api/src/api/settings.py` | New |
| `apps/api/src/api/deps/auth.py` | New |
| `apps/api/src/api/deps/db.py` | New |
| `apps/api/src/api/problem.py` | New |
| `apps/api/src/api/routers/me.py` | New |
| `apps/api/src/api/main.py` | Handlers + routers |
| `apps/api/tests/test_auth.py` | New |
| `.env.example` | `DEV_AUTH_BYPASS` |

## Test Plan

| Tier | What is covered |
| --- | --- |
| Unit | Missing auth → 401 + request_id |
| Integration | Dev auth, `/me`, cross-tenant debug + session |
| Security | Cross-tenant user visibility under RLS |

**Commands to run:**

```text
DEV_AUTH_BYPASS=true DATABASE_URL=postgresql+asyncpg://rag_app:rag_app@localhost:15432/enterprise_rag \
  DATABASE_URL_MIGRATE=postgresql+asyncpg://rag_migrate:rag_migrate@localhost:15432/enterprise_rag \
  uv run pytest apps/api/tests/test_auth.py -q
```

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Dev bypass left on in prod | Medium | Default false; document; CI can assert later |
| Identity URL misconfigured to rag_app | Medium | Fail closed (no user → 401) |

## Rollback

Revert the commit — no migration.

---

## Completion Record

- **Completed:** `2026-07-25`
- **PR:** pending
- **Evidence:** local pytest on auth + RLS
- **Work log:** pending
- **Deviations from plan:** none
- **Follow-ups raised:** none
