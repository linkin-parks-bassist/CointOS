---
status: "unverified"
created_at: "2026-09-17T18:32:26+10:00"
scope: "local"
source: "installed job task-a0c41c340fc64b1f, released inference leases, executor.py repair, and exact-session live recovery 2026-09-17"
updated_at: "2026-09-17T18:37:47+10:00"
---

On 2026-09-17 managed job `task-a0c41c340fc64b1f` was SIGTERM-terminated after ordinary tool work. Its exact OpenCode session `ses_f5185dc4fffe35QqWdheR4e2Mi` survived and both physical leases were durably released, but the durable job cycled through `reconciliation_required` and `failed` instead of resuming.

Two recovery gaps caused this. A previously completed close-out removes `executor_pid`, so `_stop_recovered_runner` could no longer prove the already-recorded stopped process group. Even when `close_runner_round` returned a completed non-cancellation outcome, the first replay branch did not promote an exact retained session back to `ready`/`continuing` unless a separate pending-preemption marker existed.

`recover_abandoned_jobs` now recognizes a matching `runner_closed_generation` plus a durable `runner_close_outcome.process_group_alive == false` as the stopped launch, reconstructs the launch record from that close outcome, and promotes any non-cancelled exact retained session to `ready`/`continuing` after close reconciliation. The installed repair live-qualified against the original stranded job: recovery returned one, cleared its reconciliation reason, preserved the same session, and dispatch generation 3 resumed it with fresh worker and inference leases.

Recheck after changing managed-runner close ordering, executor restart recovery, or exact-session continuation.
