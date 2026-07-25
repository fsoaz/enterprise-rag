# Test Evidence

> Record of what was actually run and what it showed. Not a plan — a record.
> **Related:** [../standards/testing.md](../standards/testing.md) · [work_log.md](./work_log.md) · [review_notes.md](./review_notes.md)

Claiming a task is done requires an entry here. "Tests pass" without a command and an output is not evidence.

---

## Entry format

```markdown
### E-NNN — YYYY-MM-DD — T-XXX

**Environment:** local | ci | staging
**Commit:** <short sha>

| Command | Result |
| --- | --- |
| `<exact command>` | <pass/fail + the number that matters> |

**Acceptance criteria verified:**
- [x] <criterion> — how it was checked

**Notes:** <anything surprising; skipped checks and why>
```

---

## Quality Snapshots

One row per full eval run. This table is the regression record for the whole system — the point is that a slow drift is visible across rows, not just within one run.

Targets are from [product.md § 7](../context/product.md#7-success-metrics).

| Date | Commit | Strategy | recall@10 | nDCG@10 | Faithful. | Cite prec. | Unsup. rate | Abstain (correct) | p95 e2e | Cost/query |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| *target* | — | `hybrid_rerank` | ≥ 0.90 | ≥ 0.75 | ≥ 0.95 | ≥ 0.90 | ≤ 2% | ≥ 0.90 | ≤ 4.0 s | ≤ $0.030 |
| — | — | — | — | — | — | — | — | — | — | — |

<!--
Example row once Phase 4 lands:
| 2026-10-02 | a1b2c3d | hybrid_rerank | 0.923 | 0.781 | 0.961 | 0.914 | 1.4% | 0.93 | 3.6 s | $0.024 |
-->

## Security Gate Log

Two of these must read **0**. A non-zero value blocks release regardless of anything else.

| Date | Commit | Cross-tenant leakage | ACL bypass | Injection success | RLS backstop | Log hygiene |
| --- | --- | --- | --- | --- | --- | --- |
| *gate* | — | **0** | **0** | ≤ 1% | pass | pass |
| — | — | — | — | — | — | — |

---

## Evidence Entries

### E-000 — 2026-07-25 — Planning documentation review

**Environment:** local
**Commit:** *(uncommitted — `docs/` untracked at time of review)*

No automated tests exist; the repository contains documentation only. Verification was a structured review against the plan's own criteria.

| Check | Result |
| --- | --- |
| Every internal doc link resolves to an existing file | pass |
| Every roadmap phase is referenced by an architecture section | pass |
| Every endpoint in `api_rules.md § 12` maps to a table in `architecture.md § 14` | pass |
| Locked decisions (`BGE-M3`, `pgvector`, `RRF`, `claude-opus-5`, `Next.js`, `Terraform`) appear in both architecture and the relevant standards file | pass |
| All 10 production-ready requirements have a named home and a phase | pass — see [roadmap § Cross-Phase Requirement Coverage](../context/roadmap.md#cross-phase-requirement-coverage) |
| All 6 differentiators have a named home and a phase | pass — same table |
| Model IDs, pricing, and API constraints match current Anthropic documentation | pass |
| `git status` shows documentation changes only — no code, config, or lockfiles | pass |

**Notes:** Mermaid rendering in `architecture.md § 3` was not verified in a renderer. Four open questions remain and are tracked in [product.md § 10](../context/product.md#10-open-questions) rather than resolved here — Q-1 and Q-2 are Phase 4 experiments by design.

---

<!-- Newest entries go directly below this line. -->
