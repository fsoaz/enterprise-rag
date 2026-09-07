# T-402 — Author the complete golden dataset

| Field | Value |
| --- | --- |
| ID | T-402 |
| Phase | 4 — Evaluation |
| Status | implemented locally; awaiting review and CI |
| Branch | feat/T-402-golden-dataset |
| Depends on | T-401 |
| Blocks | T-403, T-404 |

## Goal

Produce 40 validated golden cases in each of the eight documented evaluation
slices. Cases reference symbolic source-version labels, preserve expected facts,
and explicitly identify language, historical time, acting user, abstention, and
prohibited sources.

## Acceptance criteria

- Each documented slice has exactly 40 distinct, non-empty cases.
- PT/EN factual cases are balanced; cross-lingual cases cover both directions.
- Versioned cases exercise an old interval, the boundary, current behavior, and
  an absent version. Permission cases include allowed and denied users.
- Every gold and prohibited label exists in the corpus manifests; expected facts
  and date/user fields are present where required.
- Dataset generation is reproducible and fixture privacy remains enforced.

## Out of scope

Retrieval metrics and scoring, answer-quality judges, evaluation persistence/API,
CI gates, paid model calls, and dashboard UI.

## Verification

Run the deterministic builder check, dataset validator tests, Ruff, mypy, and the
full unit suite. Record skipped integration dependencies and no live-model spend.

## Rollback

Revert this commit. Dataset files are versioned artifacts; no production schema or
database data changes.

## Local verification

2026-09-07: generated and validated 320 items (40 per slice), with 10 focused
tests passing. Ruff, formatting, and mypy pass. No paid calls or CI evidence.
