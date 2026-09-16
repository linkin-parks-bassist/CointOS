---
status: "unverified"
created_at: "2026-09-14T22:40:41+10:00"
scope: "local"
source: "Independently inspected current source and design decisions in this turn; isolated real OpenCode read-back and named tests; 2026-09-14"
---

Deferring context handoffs does not remove admitted task/run/output/evidence/child/attempt budgets or scheduler/resource preemption. _run_preemptibly still accounts cumulative usage and stops at a task-budget boundary, but no longer writes a handoff-request file. The returned stop outcome includes the retained/discovered session ID.

execute_next persists usage and session identity before cleanup/reconciliation. A clean budget stop records checkpoint_required, budget_outcome and resume_available without attesting a semantic handoff or entering partial_handoff_ready. Resuming budget-exhausted work still needs an allowed budget decision; compaction itself does not grant more task authority. Deferred record_budget_handoff/checkpoint_job_state helpers remain available for future review but the active executor does not call them. Scheduler preemption remains ready with the same session. Owners: ecosystem/executor.py _run_preemptibly/execute_next; ecosystem/execution_budget.py. Tests: tests/test_cumulative_usage.py, tests/test_preemption.py, tests/test_opencode_compaction.py.
