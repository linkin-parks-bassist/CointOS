---
status: "unverified"
created_at: "2026-09-17T13:37:35+10:00"
scope: "project local"
source: "task-6827e1cc36494a7b durable record; executor.py repair; installed boundary check 2026-09-17"
updated_at: "2026-09-17T13:44:41+10:00"
---

A managed local worker previously could make no forward progress when retained-session prefill consumed nearly the entire fairness slice. `ReservePolicyDeduplicator` was dispatched seven times over about 33 minutes, repeatedly stopped with `300-second time slice expired while other work is waiting`, and made no source edit before cancellation.

The executor had started equal-priority fairness accounting immediately after process launch. It now leaves the fairness clock unset through prefill. It scans only output appended in the current runner round, scoped to the retained OpenCode session, and starts the fairness quantum when the first `step_finish` event appears. An equal-priority peer can rotate the worker only after a full productive quantum from that boundary.

Cancellation, explicit inference-allocation preemption, and higher-priority queued work are checked before the fairness clock and remain immediately preemptive. This prevents prefill livelock without weakening priority or cancellation response and without guessing a fixed prefill duration.

Source compilation and 57 existing preemption, cumulative-usage, executor, and compaction checks pass. Installed direct inspection confirmed step-boundary detection ignores `step_start`, accepts the current session's appended `step_finish`, and rejects another session.
