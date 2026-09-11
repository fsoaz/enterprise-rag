# T-408 — Chunking experiment

| Field | Value |
| --- | --- |
| ID | T-408 |
| Phase | 4 — Evaluation |
| Status | done |
| Depends on | T-407 implementation; hosted smoke evidence remains external |
| Blocks | T-409 |

## Goal

Resolve Q-1 by measuring the current fixed-token chunker against a deterministic
section-aware alternative through the production ingestion, embedding, indexing,
retrieval, and evaluation paths.

## Implementation

- `fixed_token` is the control and preserves the existing 512-token / 64-token
  overlap behavior within heading sections.
- `section_aware` packs complete Markdown headings and paragraphs up to the same
  token budget, never crosses a heading section, and uses overlapping windows only
  for oversized paragraphs.
- The worker keeps `fixed_token` as the default. `CHUNKING_STRATEGY` is an explicit
  opt-in for ingestion; the evaluation corpus loader accepts the variant directly.
- `python -m evals.harness.chunking --mode smoke --output report.json` runs both
  variants through the existing T-406 API/Celery comparison path. `--mode full`
  evaluates all 320 items.
- Reports retain dataset identity, variant identity, model configuration, all
  overall/per-slice metrics, coverage, and paired-bootstrap statistics.

## Acceptance criteria

- [x] Both variants are deterministic and have unit coverage for boundaries,
  overlap, metadata, and invalid options.
- [x] Each variant can be selected without changing the production default or
  database schema.
- [x] The experiment runner executes both variants against the same immutable
  dataset and emits separate T-406-compatible reports.
- [x] Smoke and full comparisons are run against disposable Postgres, Redis, and
  stub inference services; results are recorded as wiring evidence.
- [x] A decision is recorded as an ADR after comparing overall/per-slice recall,
  nDCG, MRR, latency, empty retrieval, tenant leakage, and ACL bypass.

## Decision rule

Keep `fixed_token` as the production default unless `section_aware` improves the
predefined retrieval metrics without introducing security failures or an
unacceptable latency increase. The full stub run matched recall and security
outcomes, with only marginal ranking differences; the control remains the
decision and the alternative is retained for real-model validation.

## Out of scope

Real-model quality claims, sparse retrieval, query expansion, new database tables,
dashboard UI, and a production-default change without measured evidence.

## Rollback

Remove the experiment runner and select `fixed_token` explicitly. Existing database
rows and migrations are unaffected.
