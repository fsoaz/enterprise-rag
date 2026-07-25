# Review Notes

> Register of review findings — self-review, peer review, `/code-review`, `/security-review`, and anything spotted in passing.
> **Related:** [work_log.md](./work_log.md) · [test_evidence.md](./test_evidence.md) · [../standards/testing.md](../standards/testing.md)

A finding outside the current task's scope goes **here**, not into the current PR. That is the mechanism that keeps PRs single-purpose without losing the observation.

---

## Severity

| Level | Meaning | Handling |
| --- | --- | --- |
| `critical` | Security hole, data loss, or cross-tenant leakage | Stop other work. Fix now. |
| `high` | Incorrect behavior in a core path, or a missing security test | Fix before the phase closes |
| `medium` | Real defect in a non-core path, or a design smell that will cost later | Scheduled into a task |
| `low` | Cleanup, clarity, minor inefficiency | Fix opportunistically |
| `info` | Observation, not a defect | Recorded for context |

## Status

`open` → `scheduled` (task ID assigned) → `resolved` (fixed and verified) · `wont-fix` (with a reason) · `duplicate` (of another ID)

---

## Register

| ID | Date | Source | Severity | Location | Finding | Status | Resolution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | *No findings yet — no code exists.* | — | — |

<!--
Row format:
| R-001 | 2026-08-03 | self | high | packages/retrieval/fusion.py:52 | RRF applied after the ACL filter instead of inside the CTE | scheduled | T-211 |
-->

---

## Standing Review Checklist

Applied to every PR, in addition to whatever the diff itself suggests. Ordered by blast radius.

### Tenancy & access control

- [ ] Every new table has `tenant_id NOT NULL` **and** an RLS policy
- [ ] `tenant_id` is derived from the JWT, never from a request parameter or body
- [ ] Every new query is tenant-scoped, and would still be safe if the ORM filter were removed
- [ ] ACL is applied **inside** the retrieval predicate, never as a post-filter
- [ ] A new endpoint returning a resource the caller cannot see returns 404, not 403, where existence is secret
- [ ] ACL cache invalidation still triggers on `acl_version` bump

### Retrieval & generation

- [ ] Retrieved content appears only in `document` content blocks — never in `system`, never concatenated into user text
- [ ] Every answer path produces resolvable citations, or downgrades the groundedness verdict
- [ ] `stop_reason` is checked before `content` is read
- [ ] Embedding calls use the correct `query` vs. `passage` mode
- [ ] A changed prompt has an eval-smoke run attached to the PR
- [ ] Nothing volatile was introduced into the cached prompt prefix

### Cost & operations

- [ ] Every new LLM call writes a `cost_ledger` row
- [ ] Prices come from the versioned table, not a constant
- [ ] New external calls have a timeout, a retry policy, and a documented degraded mode
- [ ] New metrics and log fields carry `tenant_id` and `request_id`

### Data & migrations

- [ ] Migration is reversible and `downgrade()` was exercised
- [ ] Breaking schema changes follow expand/contract
- [ ] No merged migration was edited
- [ ] Backfills are batched and idempotent

### Hygiene

- [ ] No document content, question text above `debug`, credential, or full email address in logs
- [ ] No secret in the diff; `gitleaks` clean
- [ ] `.env.example` updated for new configuration
- [ ] `openapi.json` regenerated and committed if the surface changed
- [ ] No new `skip`/`xfail` without a linked task
- [ ] Comments explain why, not what; no restated-code comments
- [ ] No abstraction added for a hypothetical second caller

### Documentation

- [ ] Behavior change reflected in `docs/context/`
- [ ] Architectural decision recorded as an ADR
- [ ] Task file's acceptance criteria all actually checked, not assumed

---

## Recurring Themes

> Patterns that show up across multiple findings. When a theme appears three times, it becomes a lint rule, a test, or a checklist item — a repeated human catch is a missing automation.

*None yet.*
