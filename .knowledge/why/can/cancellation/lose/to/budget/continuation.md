---
status: green
revised_at: "2026-09-26T05:17:25+10:00"
---

Cancellation could lose when a runner round reported both a durable cancellation and a finite-budget checkpoint. In the former `execute_next` ordering, verified runner closure was followed by the `budget_checkpoint` branch before the later `preempted` cancellation branch. With a retained OpenCode session, that earlier branch wrote `ready` and `logical_run_state: continuing`, returned immediately, and left the cancellation marker on a redispatchable job.

`ecosystem/executor.py` now calls `_complete_requested_cancellation` immediately after safe runner closure and before evaluating any continuation policy. The immediate post-close, late-preemption, and runner-exit checks use the same helper. It rereads the durable record, so cancellation wins over an outcome that also contains a budget checkpoint. Ordinary finite-budget continuation remains unchanged when no cancellation marker exists.

The full repository suite passes 858 tests, including seven temporary-root executor-round branch checks. Source and installed executor copies match after the restart-recovery repair was deployed without restarting services. Four fast filesystem-local cancellation tests cover budget precedence, ready-job relaunch prevention, durable marker preservation, and restart-recovery cancellation priority; a bounded earlier direct smoke with simultaneous cancellation, preemption, and budget-checkpoint fields reached terminal `cancelled` with `runner_close_state: cancelled` and no pending preemption. The two retained verifier jobs that exposed the defect are terminally cancelled and have no active runner; the later jobs worker lease is `quiescent` and inference lease is `released`.
