# R-070 — Guard chat inference outages

- Status: in_progress
- Branch: `test/R-070-chat-outage`
- Scope: actual chat route and retrieval pipeline under inference transport failure.
- Acceptance: streaming and JSON return exactly 503, application/problem+json,
  retrieval-unavailable; generation never starts; no dependency skips; moving
  retrieval into the stream must fail the regression.
- Out of scope: point-in-time retrieval, evaluation implementation, migration history.
- Verification: targeted pytest, Ruff, mypy, unit and deterministic security tiers.
- Rollback: revert test and documentation changes; no data or schema changes.

## Local verification

Acceptance behavior and negative mutation verified on 2026-09-06. See the dated
evidence entry. Not merged; no PR or CI confirmation. Integration security checks
remain unavailable until a disposable Postgres environment is provisioned.
