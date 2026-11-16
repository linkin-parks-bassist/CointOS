---
status: green
revised_at: "2026-11-16T12:57:45+11:00"
---

Scheduling is local. Coin takes precedence over other request classes at completed backend steps. Other current contenders share slices by a priority-weighted random draw. There are no accumulated GPU-usage scores, per-owner scheduling accounts, debt, or admission/restart history. This is David's explicit design requirement: weighted random choice supplies rough parity without tracking past service. Separate engines still contend independently.

**Draw and clocks.** Each scheduling client receives a stable draw for the current global slice, using u^(1/weight); the highest eligible draw wins. The next slice redraws it. Managed clients use agent identity; user requests use their session owner (request ID when no distinct owner exists). Draws, placement, turn clocks and tool grace use that same identity. Seeding all private windows as `user` produced identical draws and insertion-order starvation; grace could also leak across windows. Equal-class holders retain an unexpired slice, unsaved reads and bounded tool grace; Coin bypasses those peer protections. Checkpointed/resident partial reads can participate after their slice expires. Completing an opening read earns a generation slice; short tool follow-ups do not restart its clock. Reading counts toward the current slice. Backend calls finish before reassignment, so slow steps can still delay Coin. Probability supplies rough allocation, not a maximum wait or exact physical-time parity.

**Weights/settings.** scheduler.weights owns Coin 1000, user/Operator 100, First Responder 4, Supervisor/integrator 3, worker/manager/Steward 2 and other/taskless background 1. Coin's responsiveness comes from precedence, not accumulated service. User/Operator and ordinary work share weighted draws. request_class can demote Coin to background without changing identity; elevation is refused. Task-drawer overrides persist only the requested weight, update current thoughts and preserve keys/sessions; role default clears the override. They create no scheduling account. Live slice/step values come from ledger.scheduler; installation preserves them. Never infer effective values from static HTML options or source defaults; repair display/readback mismatches without resetting settings.

**Placement.** Prefer own/kept, warm and free lanes, then generating holders before readers and the holder with the lowest draw. Reserved lanes and paused/blocked classes remain authoritative. Resident state or a successful checkpoint preserves displaced preparation. Failed optional checkpoint admission protects a peer read, but never gives it precedence over Coin. Shared-prefix/tail persistence remains separate from placement. Long prompts checkpoint 32 tokens before the prepared end; a warm prefix beyond it freezes that later position.

**Checks and evidence.** A Coin waiter blocked beyond checks.preempt_seconds after the holder's slice fails health even behind an unsaved read and regardless of obsolete score fields. Other eligible waiters fail when a winning current draw is unapplied after the slice/grace allowance; losing a lottery alone is not a fault. The check clock does not reset each short slice. Stalled-held-thought checks remain separate. Tests cover historical-score independence, weighted odds, Coin preemption, slices, grace, reservations, partial reads, priority changes, restart and admission. The preemption evidence owner retains native deployment and latency limits; unit checks do not establish useful autonomous throughput or fifteen-second replies.

Proof:

```bash
python3 -m unittest -q tests.test_live_priority tests.test_scheduler_service tests.test_scheduler tests.test_memory_and_checks tests.test_turns tests.test_run_admission tests.test_request_class
```
