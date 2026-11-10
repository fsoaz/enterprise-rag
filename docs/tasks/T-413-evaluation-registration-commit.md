# T-413 — Commit evaluation registration before responding

Status: done (merged; hosted CI verified in E-019). Branch: docs/T-412-documentation-accuracy-audit (user requested
CI remediation alongside PR #5's preserved AGENTS.md changes).

## Goal

An evaluation dataset and its items are committed before registration returns 201,
so an immediate run request on another connection can see them.

## Context

PR #5 CI run 37084904321 failed with `Evaluation dataset not found`. Request-scoped
dependency cleanup commits after the response can reach a real HTTP client.
See [architecture](../context/architecture.md#11-evaluation-architecture).

## Acceptance Criteria

- [x] Registration commits before returning and propagates commit failures.
- [x] Regression checks visibility before dependency cleanup and tenant denial.
- [x] Offline checks, integration tests, and deterministic smoke gate pass.

## Scope and Design

Commit dataset and items together in the registration route; retain existing RLS,
authorization, schemas, baseline, and AGENTS.md. No migrations or dependencies.
Expected files: evaluation router/tests and task/execution/architecture documentation.
Rollback: revert the fix; no schema changes.

## Test Plan

Run lint/typecheck/unit tests, disposable integration tests, OpenAPI drift checks,
and the production-path deterministic smoke comparison and thresholds.

## Verification

See E-018 in [test evidence](../execution/test_evidence.md).

## Hosted reconciliation — 2026-11-09

Fix `6b3e2c5` merged in PR #5 as `353820d`. PR CI run
[37093710003](https://github.com/fsoaz/enterprise-rag/actions/runs/37093710003)
passed all seven jobs, including the smoke comparison and threshold enforcement;
post-merge run [37094247061](https://github.com/fsoaz/enterprise-rag/actions/runs/37094247061)
also passed. E-018 remains historical local evidence; E-019 records the hosted
results and their limits. No hosted validation remains pending for this fix.
