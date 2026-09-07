# T-401 — Expand and validate the synthetic evaluation corpus

| Field | Value |
| --- | --- |
| ID | T-401 |
| Phase | 4 — Evaluation |
| Status | implemented locally; awaiting review and CI |
| Branch | feat/T-401-fixture-corpus |
| Depends on | R-030 |
| Blocks | T-402 |

## Goal

Provide source material for at least 40 distinct cases in each documented slice,
with balanced PT/EN sources, exact version labels, cross-document joins, restricted
facts, hostile documents, and a second tenant with conflicting facts.

## Acceptance criteria

- Forty distinct synthetic operational scenarios, 20 PT and 20 EN; each has two
  dated policy versions, a separate routing record, and a restricted record.
- Forty adversarial source documents cover all eight documented attack families,
  including coordinated documents; PT/EN are balanced. Payloads use harmless
  evaluation markers, without real credentials or external destinations.
- A second-tenant manifest contains forty conflicting counterparts, allowing
  leakage tests whose answers cannot be inferred from the first tenant's corpus.
- Manifest labels, paths, source hashes, dates, collections, scenario links and
  privacy are validated; malformed corpora fail before any DB or inference work.
- Every source parses and chunks through the existing worker code; a disposable
  Postgres check loads both tenant corpora with deterministic embeddings and
  validates counts, version mapping, tenant boundaries and repeat loading.
- Existing golden labels remain available. No quality score or baseline changes.

## Out of scope

Golden question authoring and grading (T-402), metrics/judges, run APIs, CI gates,
paid generation, production retrieval/chunking defaults, and migration history.
Markdown sources are sufficient here; parser format support is already separate.

## Design and verification

Use an explicit authoring catalog and reproducible checked-in Markdown/manifest
artifacts. Metadata is never concatenated into source text as answer instructions.
Use fixed UTC validity intervals. Corpus registration must validate before writes.
Run Ruff, format, mypy, full unit suite, fixture mutation tests, and dedicated
Postgres integration; record environment and all skips. No new dependency.

## Rollback

Revert this task's changes; discard the disposable evaluation DB. No production
schema/data changes and no changes to released migrations.

## Local verification

2026-09-07: corpus renderer check passed for 247 artifacts. Manifest and metrics
tests passed (8 tests); full suite passed with 122 passed, 1 existing dependency
skip, and 19 integration deselections. Ruff, formatting, and mypy passed. No paid
calls or CI evidence. Disposable Postgres loading is deferred to the dedicated
T-402/T-405 database checks; no production database was modified.
