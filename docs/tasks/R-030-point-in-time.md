# R-030 — Retrieve exact historical document versions

- Status: implemented locally; awaiting review and CI
- Branch: `feat/R-030-point-in-time` (stacked on R-070)
- Acceptance: optional ISO date or timezone-qualified timestamp on search/chat;
  date maps to midnight UTC; timestamps normalize to UTC; invalid/naive values fail.
  Both retrieval arms apply effective_from <= as_of < effective_to, null upper bound
  allowed. Omission retains current versions. Present tenant, ACL, archival,
  erasure and injection controls remain active. Lexical fallback and service
  callers carry as_of; dataset dates reach retrieval; citations retain version IDs.
- Out of scope: date UI, changing ACL rules, evaluation foundation, migration history.
- Verification: interval boundaries, strategies, fallback propagation, API validation,
  SQL security predicates, Ruff/mypy/unit, integration when services are available,
  generated OpenAPI and frontend types.
- Rollback: revert code/contracts; no schema or data changes.

## Local verification

2026-09-06 evidence recorded in test_evidence.md. 116 unit passes, one existing
dependency skip, 19 integration deselections; 4 dedicated Postgres integration
passes without skips. Ruff/mypy/import contracts/OpenAPI/frontend types pass.
No released migration changed. No PR/merge/CI or release-readiness claim.
