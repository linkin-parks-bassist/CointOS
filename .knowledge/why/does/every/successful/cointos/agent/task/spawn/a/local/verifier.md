---
status: green
revised_at: "2026-09-26T06:43:42+10:00"
---

It no longer does. Previously, `executor.execute_next()` converted every ordinary `run_finished` task to `awaiting_verification` and called `verification.enqueue()`; the watchdog then recreated any missing verifier. A read-only survey therefore spawned a Qwen verifier which competed with production work.

Successful ordinary tasks now transition directly to terminal `completed`, persist `completed_at`, and queue their normal notification. Verification is explicit opt-in: `cli.enqueue_task(..., verification_requested=True)` or `ecosystem enqueue --verify` records the request. Only a successful job with that exact boolean enters `awaiting_verification` and spawns the independent verifier. The watchdog still repairs a missing verifier for that deliberate state. New verifier enqueues now persist the target link atomically with a deterministic idempotency key, so a replay cannot spawn a duplicate; this is installed without a service restart and live qualification remains pending.

Installed direct intake qualification recorded `verification_requested: false` for an ordinary job and `true` for an explicit job. Source compilation and 74 existing compaction, executor, control-turn, task-contract, and intake checks pass. No new regression test was added.
