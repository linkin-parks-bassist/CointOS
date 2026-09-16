---
status: "unverified"
created_at: "2026-09-15T22:36:28+10:00"
scope: "CointOS agent execution"
source: "source and installed unlimited-budget execution qualification through 2026-09-16"
updated_at: "2026-09-17T09:55:56+10:00"
---

Ordinary CointOS agent tasks no longer have arbitrary run-time, task-time, attempt, output-byte, or evidence ceilings. Task contracts represent an absent ceiling as `None`; verification, scheduled-review, sole-survivor, and authenticated-contact constructors use that form. `deadline_monotonic: None` is carried through worker acquisition, and the executor does not compare elapsed time for an unlimited task.

Finite budgets remain supported for deliberately bounded probes or specialized contracts. If a finite budget is exhausted and an exact OpenCode session exists, the executor performs verified runner cleanup and queues the same job as `ready`/`continuing`, clears slice usage, records `task.budget_continuation_queued`, and resumes with `--session`. A missing exact session remains an emergency `checkpoint_required` outcome because CointOS cannot truthfully claim continuation identity.

Child ceilings remain possible authority/scope bounds rather than agent-lifetime limits. Unexpected ready-state setup errors retain one visible `last_executor_error` and stop the activation instead of hot-looping. Installed qualification confirmed an unlimited authenticated-contact task reached a real OpenCode process with `deadline_monotonic: None`; live cancellation later ended with worker quiescent, inference released, and credential revoked.