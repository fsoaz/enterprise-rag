# T-XXX — <short imperative title>

> Copy this file to `docs/tasks/T-XXX-<slug>.md` and fill it in **before** writing code.
> Delete the instruction lines in angle brackets as you go.
> See [README.md](./README.md) for numbering and lifecycle.

| Field | Value |
| --- | --- |
| **ID** | `T-XXX` |
| **Phase** | `<0–7 — see roadmap.md>` |
| **Status** | `planned` |
| **Branch** | `<type>/T-XXX-<slug>` |
| **Size** | `S` \| `M` \| `L` |
| **Depends on** | `<task IDs, or "none">` |
| **Blocks** | `<task IDs, or "none">` |

---

## Goal

<One or two sentences. What is true after this task that is not true now? Written as an outcome, not as a list of steps.>

## Context

<Why this task exists and what a reader needs to know to do it. Link the relevant design sections rather than restating them.>

- Design: [architecture.md § X](../context/architecture.md)
- Product: [product.md § X](../context/product.md)
- Stories satisfied: `<KS-n, KW-n, PA-n>`
- Prior findings: `<review_notes.md IDs, if any>`

## Acceptance Criteria

<Testable statements. Each one must be verifiable by running something. If you cannot describe how to check it, it is not a criterion yet.>

- [ ] …
- [ ] …
- [ ] …

## Out of Scope

<Explicitly list what this task does **not** do, especially the adjacent things a reader would assume are included. This field is what prevents scope creep — do not leave it empty.>

- …
- …

## Design Notes

<Approach, key decisions, alternatives considered and rejected. If a decision here is architectural, it also becomes an ADR in architecture.md § 15.>

## Files Expected to Change

<Best-guess list. Being wrong is fine; the point is to surface unexpected blast radius before starting.>

| Path | Change |
| --- | --- |
| `packages/…` | |
| `apps/…` | |
| `docs/…` | |

## Data / Migration Notes

<Delete this section if there is no schema change.>

- Tables touched:
- Migration is reversible: yes / no (must be yes)
- Expand/contract needed: yes / no
- Backfill required: yes / no — if yes, batched and idempotent?
- RLS policy added for any new tenant-scoped table: yes / n-a

## New Dependencies

<Delete if none. Required by [ai_agent_rules.md § A5](../standards/ai_agent_rules.md#a5-dependencies).>

| Package | Why | Why not stdlib / existing | Licence | Last release |
| --- | --- | --- | --- | --- |

## Test Plan

| Tier | What is covered |
| --- | --- |
| Unit | |
| Integration | |
| Contract | |
| Security | <required if this touches tenancy, ACL, auth, or prompt construction — otherwise state "n/a: does not touch security surface"> |
| Eval | <required if this touches retrieval or generation — otherwise "n/a"> |
| E2E | |

**Commands to run:**

```text
<the exact commands a reviewer can run to verify>
```

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |

## Rollback

<How to undo this if it goes wrong in staging or production. "Revert the commit" is only sufficient when there is no migration and no data change — say so explicitly if that is the case.>

---

## Completion Record

<Filled in when the task is done.>

- **Completed:** `<YYYY-MM-DD>`
- **PR:** `<link>`
- **Evidence:** [test_evidence.md](../execution/test_evidence.md) entry `<id>`
- **Work log:** [work_log.md](../execution/work_log.md) entry `<date>`
- **Deviations from plan:** `<what changed and why, or "none">`
- **Follow-ups raised:** `<task IDs or review_notes IDs, or "none">`
