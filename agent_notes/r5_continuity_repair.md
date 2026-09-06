# R5 active-run quota repair (Sieve, local Qwen3.8 worker, 2026-09-06)

Bounded repair assigned by coordinator Astra; worktree
`cointos-mvp-budget-continuity`, base `2d754f2`.

## Defect

`execution_budget.budget_outcome` applied `total >= limit` to every field.
`executor._run_preemptibly` seeds usage from the already started job
(`attempts` = the running attempt), so an admitted first attempt
(`maximum_attempts=1`, `attempts=1`) checkpointed immediately, and any parent
forbidden from creating children (`maximum_children=0`, `children=0`) was
stopped before it could run.

## Repair (budget owner only)

Per-check exhaustion predicates in `execution_budget.py`: continuous usage
(task/run seconds, output bytes, evidence items) exhausts at the ceiling
(`_reached_ceiling`, `>=`); admitted counts (the running attempt, created
children) exhaust only when the quota is exceeded (`_exceeded_ceiling`, `>`).
No executor change: it already accounts the admitted attempt, and the budget
owner now interprets that correctly. Actual overruns still checkpoint
(`attempts > maximum_attempts`, `children > maximum_children`); field order
and time/output exhaustion are unchanged. Child admission itself remains
enforced at delegation time (`cli.enqueue_child`, `narrow_contract`), so this
weakens nothing.

## Tests (written before the fix, demonstrated failing)

- `tests/test_preemption.py`: `test_first_admitted_attempt_runs_with_zero_child_quota`
  — real short-lived child, `maximum_attempts=1`, job `attempts=1`,
  `maximum_children=0`; completes normally, no `budget_checkpoint`.
- `tests/test_execution_budget.py`: admitted first attempt / zero child quota
  stays `within_budget`; actual attempt and child overruns still yield
  `checkpoint_required` with the owning reason.

Focused: budget 10/10, preemption 4/4. Full suite 504/504.

## Unfinished (separate follow-ups; this repair does NOT complete R5/R6)

- Cumulative task time/output persistence across continuation rounds.
- Double-charging risk: cumulative usage must not be compared against an
  already-decremented remaining budget; keep one consistent accounting
  representation at the budget owner, exercised with literal two-round totals.
- Known R4 gap: persist accounting before the normal-close/reconciliation
  branch so observed usage cannot be discarded; backend-close smoke still
  needs the Lemonade-side observer.
