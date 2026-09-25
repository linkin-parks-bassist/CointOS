---
status: green
revised_at: "2026-09-17T19:51:46+10:00"
---

A managed local worker previously could make no forward progress when retained-session prefill consumed nearly the entire fairness slice. `ReservePolicyDeduplicator` was dispatched seven times over about 33 minutes, repeatedly stopped with `300-second time slice expired while other work is waiting`, and made no source edit before cancellation.

The executor now leaves the fairness clock unset through prefill. It scans only output appended in the current runner round, scoped to the retained OpenCode session, and starts the fairness quantum when the first `step_finish` event appears. An equal-priority peer can rotate the worker only after a full productive quantum from that boundary.

A second defect violated the equal-priority rule after productive work began: `_preemption_reason` rotated the running job after the quantum for any waiting job that was not higher priority, including a lower-priority periodic Steward review. This interrupted user-directed builder `task-af1fb27399d66898` after it had edited and compiled its target. The installed repair computes the strongest waiting and running priorities once, preempts immediately when waiting priority is higher, returns no preemption when it is lower, and applies the fairness quantum only when the priorities are equal. The builder's exact OpenCode session was retained and resumed.

Cancellation, explicit inference-allocation preemption, and higher-priority queued work are checked before the fairness clock and remain immediately preemptive. This prevents prefill livelock and lower-priority interruption without weakening priority or cancellation response and without guessing a fixed prefill duration.

The original source compilation and 57 existing preemption, cumulative-usage, executor, and compaction checks passed. Installed direct inspection confirmed step-boundary detection ignores `step_start`, accepts the current session's appended `step_finish`, and rejects another session. The lower-priority repair passed source compilation and installed retained-session recovery; live no-preemption qualification across a full quantum remains the next check.
