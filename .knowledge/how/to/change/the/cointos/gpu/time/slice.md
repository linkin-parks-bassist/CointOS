---
status: green
revised_at: "2026-11-17T10:08:17+11:00"
---

The active runtime owns two scheduler settings that change without process replacement:

- `scheduler.slice_seconds`: the normal turn quantum; Coin may preempt it at a completed GPU step.
- `scheduler.chunk_tokens`: the maximum generation tokens in one GPU step.

Change them through the dashboard Machine panel or `POST /api/scheduler` with either or both fields. The API validates the complete resulting pair and persists it before applying it. Direct edits to the active runtime's `config/cointos.json` are noticed each daemon tick. Editing source does not affect installed runtime.

`slice_seconds` must be finite and positive. `chunk_tokens` must be a positive integer, never a boolean. Invalid/partial configuration retains the last valid pair and exposes `config_error`. The ledger's `scheduler` object is the authority for effective values. Dashboard controls follow it even while focused, show a separate Running value, and show no numeric default before connection. Successful saves use the daemon's acknowledged pair immediately; failed saves retain the prior live value. Settings render before unrelated panels so a panel error cannot leave a plausible stale control. A displayed/running mismatch requires repairing readback, not resetting to the displayed number.

Gufo streams tokens within each generation step, independently of `chunk_tokens`. Halogen currently delivers the validated vector after the complete step; smaller steps therefore improve its display cadence but add boundary overhead. The Halogen integration owner records the measured trade-off.

Reading and generation both count toward the current slice. An opening read earns a generation slice on completion; Coin may preempt it at a completed GPU step. Short tool follow-ups retain the turn clock and Coin bypasses their locality preference. Checkpointed readers may yield before completion. A shorter slice takes effect at a completed GPU step; no in-flight request is cut. Tool grace never extends past the slice end. Workers read `chunk_tokens` at step start: an in-flight step finishes at its old size, and the next uses the new value without losing tokens.

Source defaults are 32-token steps and 10-second slices. The installed runtime is currently 8-token steps, 5-second slices and 1024-token read chunks (ledger.scheduler), tuned for smoother Halogen delivery; verify live values from that object. In resident mode an owner change selects a slot with no KV copy. Historically, at a 70k Qwen context under concurrent Coin load, 96-token steps reached about 25 seconds and triggered the 15-second overdue-preemption check; 32-token steps reduced that stall. Preserve live user settings across compatible upgrades; this is not authority to reset the current pair. Verify waiting-agent progress and check recovery; token count cannot guarantee a wall-time bound.

Step size and slice are independent. Smaller steps improve pre-emption granularity but add transport, serialization, pending-token consumption and scheduling overhead. Actual switches can add snapshot costs. Measure the throughput trade-off under representative load; short benchmarks made with 96-token steps do not establish current live throughput.

No model shape or weight reload is required. Older installed code needs compatible installation before these fields reload. `how/to/restart/cointos.md` owns larger replacement choices.

Per-agent priority is separate: open its active task drawer, set GPU priority (a positive finite weight) and Apply, or choose Role default. POST /api/agent-priority takes task and weight; null restores the configured role weight. The override is stored on the task and affects pending/future thoughts without restarting the agent. The new weight changes local random-draw odds; no usage history or debt is stored. Tests cover real allocation semantics, invalid values and preserved session/budget identity. Project queue priority controls admission separately.
