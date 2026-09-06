# R5 cumulative usage across runner rounds (Sieve, local Qwen3.8 worker, 2026-09-06)

Bounded repair assigned by coordinator Astra; worktree `cointos-mvp-cumulative-usage`, base `99170fb` (R5 quota repair).

## Defect

`_run_preemptibly` seeded usage from attempts only (ignoring
`job.budget_usage`), returned live markers or no usage at all, and missed
final output bytes after the last poll or during wrap-up. `execute_next`
persisted usage only on the checkpoint branch after `close_runner_round`,
so the reconciliation early return and preemption/normal paths lost all
accounting; the output baseline was sampled after launch, so fast startup
writes escaped.

## Repair (executor only; execution_budget.py unchanged)

- Seed usage from persisted `budget_usage`: keep task_seconds, output_bytes,
  evidence_items, children; drop live markers; reset run_seconds each round;
  attempts policy unchanged (job counter).
- New `_close_usage` closes run/task intervals and counts final output; all
  three returns (normal, preempted, budget stop) return closed usage.
- `execute_next` captures the pre-launch output offset (truncated=0,
  appended=current size) via optional `initial_output_bytes` and persists
  `budget_usage` atomically right after the runner returns, before
  close/reconciliation. Close-state and cancellation ordering unchanged.

## Tests (red first, then green; deterministic fakes, no classes)

`tests/test_cumulative_usage.py`: two rounds 3s+4s with a 100s queue gap =>
task_seconds 7, run_seconds 4, output_bytes 5+7=12, no live markers;
persisted near-limit usage checkpoints a later round (reason task_seconds);
preemption returns closed usage with final output; `execute_next`
reconciliation path persists closed usage. Red 4/4; green 4/4; focused
18/18; full suite 508/508 OK. R5 not fully closed: double-charging audit
and R4 normal-close observation remain separate follow-ups; R6 untouched.
