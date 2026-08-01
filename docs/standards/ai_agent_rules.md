# AI Agent Rules

> **Applies to:** AI coding agents working in this repository, and to humans reviewing their output.
> **Related:** [conventions.md](./conventions.md) · [testing.md](./testing.md) · [api_rules.md](./api_rules.md) · [../context/architecture.md](../context/architecture.md)

Two parts. **Part A** governs how an agent works in this repo. **Part B** governs the LLM code the agent writes — these are correctness rules, and violating them produces a 400 from the API or a silently broken product.

---

# Part A — Working in This Repository

## A1. Before changing anything

1. Read [product.md](../context/product.md) and [architecture.md](../context/architecture.md). The design is decided; do not re-derive it.
2. Read the task file in `docs/tasks/` for the task you are on. If none exists, create one from [TEMPLATE.md](../tasks/TEMPLATE.md) before writing code.
3. Check [current_task.md](../execution/current_task.md) — if another task is in progress, do not start a second one.
4. Check [review_notes.md](../execution/review_notes.md) for open findings in the area you are touching.

## A2. Scope discipline

- **One task per branch, one task per PR.** A PR touching three unrelated areas gets split.
- The task file's acceptance criteria are the scope. Do not quietly widen it, and do not quietly narrow it.
- Found a real problem outside your scope? Record it in [review_notes.md](../execution/review_notes.md) and keep going. Do not fix it in this PR.
- If a requirement turns out to be wrong or impossible, say so in one or two sentences, then deliver the rest under a stated assumption. Scaling work down is the user's call.

## A3. Never do these without asking

- Delete or rewrite a migration that has been merged
- Drop a table, a column, or an index
- Change an ACL, RLS policy, or tenant-scoping rule as a side effect of another change
- Force-push, rewrite history, or push directly to `main`
- Add a new external service or paid dependency
- Disable, skip, or loosen a security test
- Change an eval baseline without an explanation in the PR
- Commit anything that looks like a credential

## A4. Always do these

- Run `ruff`, `mypy`, and the unit + security tiers before claiming a task is done
- Write the migration's `downgrade()` and exercise it
- Update `.env.example` when adding configuration
- Regenerate and commit `openapi.json` when the API surface changes
- Append an entry to [work_log.md](../execution/work_log.md) on completion
- Record verification evidence in [test_evidence.md](../execution/test_evidence.md)
- Update [current_task.md](../execution/current_task.md) when starting and finishing

## A5. Dependencies

A new dependency requires a note in the task file covering: what it does, why the standard library or an existing dependency will not serve, its licence, its last release date, and its maintenance status. Prefer the standard library. Prefer a small library over a framework.

## A6. Reporting

- Report outcomes faithfully. If tests fail, say so and paste the output. If a step was skipped, say which and why.
- Do not claim completion until every acceptance criterion is met and verified.
- No hedging on work that is actually done — state it plainly.
- Do not fabricate a test result, a metric, or a benchmark number. If it was not run, say it was not run.

## A7. Code style expectations

Full rules in [conventions.md](./conventions.md). The ones agents get wrong most often:

- Match the surrounding code's idiom, comment density, and naming. New code should be indistinguishable from what is already there.
- Comments explain **why**, never **what**. A comment restating the next line is deleted in review.
- No defensive error handling for conditions that cannot occur. Validate at system boundaries only.
- No abstraction for a hypothetical second caller. Two concrete callers, then abstract.
- No helper file, no new module, and no new configuration option unless the task calls for it.

---

# Part B — LLM Integration Rules

Every rule here is either an API constraint (violating it returns a 400) or a product invariant (violating it ships a broken feature). None of them are stylistic.

## B1. Models

| Purpose | Model ID | Price (in/out per MTok) |
| --- | --- | --- |
| Answer generation | `claude-opus-5` | $5 / $25 |
| Degraded generation | `claude-sonnet-5` | $3 / $15 |
| Judging, expansion, classification | `claude-haiku-4-5` | $1 / $5 |

- Model IDs are **exact strings**. Never append a date suffix — `claude-opus-5`, not `claude-opus-5-20260401`.
- Never downgrade a model to save cost without an explicit decision recorded in the task file. Cost is the operator's call, not the agent's.
- Model IDs come from a registry in `packages/llm`, never from a string literal at a call site.

## B2. Request-shape constraints (these return 400 if violated)

| Rule | Detail |
| --- | --- |
| **Adaptive thinking only** | `thinking: {"type": "adaptive"}`. `budget_tokens` is removed on Opus 5 and returns 400. |
| **Thinking is on by default** on `claude-opus-5` | Omitting `thinking` runs adaptive. `max_tokens` caps thinking **plus** answer — size it for both or responses truncate mid-answer. |
| **Disabling thinking is effort-capped** | `thinking: {"type": "disabled"}` is accepted only at `effort` ≤ `high`. Pairing it with `xhigh` or `max` returns 400. |
| **No sampling parameters** | `temperature`, `top_p`, `top_k` return 400 on Opus 5. Steer with prompting. |
| **No assistant prefill** | A trailing `role: "assistant"` message returns 400. Use `output_config.format` or a system-prompt instruction. |
| **Effort lives in `output_config`** | `output_config: {"effort": "high"}` — not a top-level parameter. |
| **Stream above ~16k `max_tokens`** | Non-streaming requests at high `max_tokens` hit SDK HTTP timeouts. |
| **Citations and structured output are mutually exclusive** | `citations: {enabled: true}` plus `output_config.format` returns 400. Split into two calls. |

## B3. Response handling

- **Check `stop_reason` before reading `content`.** A refusal returns HTTP 200 with empty or partial content. `response.content[0].text` without that check is a crash waiting for a specific input.
- Handle `pause_turn` in the tool loop by re-sending the conversation; cap continuations at 3.
- Handle `max_tokens` distinctly from `end_turn` — a truncated answer must not be served as complete.
- Enable server-side fallbacks by default: `fallbacks: "default"` with beta header `server-side-fallback-2026-07-01`, so a safety refusal is re-served rather than surfacing as a failure.
- Iterate `content` blocks by `type`. Never index a fixed position.

## B4. Retrieved content is untrusted input

This is the rule with the largest blast radius if broken.

- **Retrieved document text goes only into `document` content blocks.** Never into `system`. Never string-concatenated into the user's message text.
- Runtime operator instructions use mid-conversation `{"role": "system"}` messages — the non-spoofable channel. Never a `<system-reminder>`-style text block inside a user turn, which document content can imitate.
- The system prompt states explicitly that document content is data to summarize and cite, never instructions to follow.
- No tool with side effects is exposed to the model. Read-only allowlist, ACL-bound, capped call count.
- Every answer passes the egress scan before leaving the API.

## B5. Citations are mandatory

- Use **native Anthropic citations** — `document` blocks with `citations: {enabled: true}`. Do not implement prompt-numbered `[1]`/`[2]` markers; the model can fabricate a number it never read, and it cannot fabricate an API-returned span.
- Every `document_index` in the response is mapped back to a `chunk_id` and `document_version_id` and persisted to `query_citations`. An unmapped citation is a bug.
- **An answer with uncited claims is a defect, not a style issue.** It must be caught by the groundedness check and downgraded to `partial` or `unsupported`, not served as `grounded`.

## B6. Cost accounting

- **Every LLM call writes a `cost_ledger` row.** Generation, judging, expansion, eval — no exceptions. An un-ledgered call is a review-blocking defect, and a test counts calls against rows.
- Record `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, model, purpose, latency, and the `price_table_version` used.
- Prices come from the versioned `model_prices` table, never from a constant in code.

## B7. Prompt caching

- The stable prefix is the system instructions plus the tenant policy block, with the `cache_control` breakpoint on the last system block. Everything volatile goes after it.
- **Nothing dynamic in the system prompt** — no `datetime.now()`, no request ID, no user name, no per-request counter. A single volatile byte invalidates the whole prefix.
- Tool definitions are serialized deterministically (sorted by name). Changing the tool set mid-conversation invalidates the cache.
- Verify with `usage.cache_read_input_tokens`. Zero reads across repeated queries means a silent invalidator, and it is a bug to be fixed, not a metric to be ignored.
- Minimum cacheable prefix on `claude-opus-5` is 512 tokens.

## B8. Prompts live in files

- Prompt templates live in `packages/llm/prompts/`, versioned, one file per prompt.
- Judge rubric prompts additionally carry a hash recorded on `eval_runs.judge_prompt_hash`.
- Changing a prompt requires an eval-smoke run attached to the PR. A prompt change is a behavior change.
- No prompt string is constructed inline at a call site.

## B9. Embeddings and reranking

- Both go through the `inference` service's HTTP contract. Neither `api` nor `worker` loads model weights.
- BGE-M3 uses **different instruction prefixes for queries and passages** — `mode: "query"` when embedding a user query, `mode: "passage"` when embedding a chunk. Using the wrong one measurably degrades recall and produces no error.
- Embeddings are written with `model_name` and `model_version`. Retrieval filters to the active generation. Changing the embedding model is a reindex, not an in-place update.

## B10. When in doubt about the Anthropic API

Do not guess a parameter name, a model ID, or a response field. The rules above are the repo's summary; the authoritative source is Anthropic's current documentation. If a needed detail is not covered here, look it up before writing the call — an invented parameter fails at runtime, in production, on a specific input.
