# Tasks

One file per task. A task is the unit of work that maps to one branch and one pull request.

> **Related:** [TEMPLATE.md](./TEMPLATE.md) · [../context/roadmap.md](../context/roadmap.md) · [../execution/current_task.md](../execution/current_task.md)

---

## Numbering

`T-<phase><seq>` — phase digit, then a two-digit sequence.

| ID | Meaning |
| --- | --- |
| `T-001` | Phase 0, task 1 |
| `T-104` | Phase 1, task 4 |
| `T-205` | Phase 2, task 5 |
| `T-710` | Phase 7, task 10 |

Phases are defined in [roadmap.md](../context/roadmap.md). Each phase there lists its planned task IDs — those are the reservations. A task discovered mid-phase takes the next free sequence number in that phase and gets added to the roadmap's task list in the same PR.

Filename: `T-205-rrf-fusion.md`. Branch: `feat/T-205-rrf-fusion`.

## Lifecycle

```text
planned → in_progress → in_review → done
                    ↘ blocked ↗
                    ↘ abandoned
```

| State | Meaning | Where it shows |
| --- | --- | --- |
| `planned` | File exists, work has not started | Task file |
| `in_progress` | Branch created, work underway | Task file + [current_task.md](../execution/current_task.md) |
| `blocked` | Waiting on a decision or another task | Task file, with the blocker named |
| `in_review` | PR open | Task file |
| `done` | Merged, criteria verified, evidence recorded | Task file + [work_log.md](../execution/work_log.md) |
| `abandoned` | Not doing it. Reason recorded in the file; file kept. | Task file |

## Rules

1. **A task file exists before code is written.** If you find yourself coding without one, stop and write it — the acceptance criteria are what makes "done" checkable.
2. **One task in `in_progress` at a time.** [current_task.md](../execution/current_task.md) points at exactly one.
3. **Acceptance criteria are testable statements**, not intentions. "Retrieval is fast" is not a criterion; "retrieval-only p95 ≤ 400 ms on a 100k-chunk corpus" is.
4. **Out-of-scope is filled in, not left blank.** It is the field that prevents scope creep.
5. **A task that grows past a week gets split.** Update the roadmap when you split it.
6. **Task files are not deleted.** An abandoned task keeps its file with the reason — the record of what was decided against is worth as much as the record of what was built.

## Completing a task

1. Every acceptance criterion verified — actually run, not assumed.
2. [Definition of Done](../standards/conventions.md#13-definition-of-done) satisfied.
3. Evidence recorded in [test_evidence.md](../execution/test_evidence.md).
4. Entry appended to [work_log.md](../execution/work_log.md).
5. Any findings outside scope logged in [review_notes.md](../execution/review_notes.md).
6. Task file status set to `done`; [current_task.md](../execution/current_task.md) advanced to the next task.
