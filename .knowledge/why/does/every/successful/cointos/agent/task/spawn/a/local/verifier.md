---
status: "unresolved"
created_at: "2026-09-17T12:58:18+10:00"
scope: "project local"
source: "executor.py, verification.py, watchdog.py and installed ReserveConstantSurveyor verifier incident 2026-09-17"
checked_at: "2026-09-17T12:58:18+10:00"
blocker: "Automatic verification is unconditional in executor.py and watchdog.py, but an explicit opt-in task-contract field is not yet implemented."
next_check: "After the active reserve-policy worker closes, add an explicit verification request field or direct successful ordinary MVP tasks to completed, then update watchdog reconciliation and existing checks."
---

`executor.execute_next()` currently converts every ordinary `run_finished` task to `awaiting_verification` and calls `verification.enqueue()`. That function creates a second local reasoning/tool worker with an independent-verification contract. `watchdog.reconcile_verifications()` recreates a verifier whenever an awaiting task lacks one. No task-type, acceptance, cost, risk, or explicit operator decision gates this behavior.

During the read-only `ReserveConstantSurveyor` inventory, this automatically spawned `verifier-4b5771` on Qwen3.8. The verifier repeatedly won scheduling and deferred on physical capacity, temporarily starving the actual production coder queued afterward. It was caller-scoped cancelled. This behavior conflicts with the current global MVP policy to spend local-worker time on production code and avoid default regression/verification work.

Desired direction: successful ordinary tasks complete directly. Preserve independent verification as an explicit tool for work whose contract or operator asks for it; do not have the watchdog manufacture it merely because a process exited successfully. Exact opt-in schema and compatibility disposition remain to be implemented.
