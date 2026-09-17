---
status: "unresolved"
created_at: "2026-09-17T20:30:41+10:00"
scope: "local"
source: "task-a7bd8e22058c4418 one-file retention mapping 2026-09-17"
updated_at: "2026-09-17T20:43:29+10:00"
---

Installed `worker_lease_health` first reported 2,084 quiescent leases in generation 3 with mode open. `workload_control.py` never deletes or bounds `state["leases"]`; every dirty save rewrites the whole accumulated document.

Quiescent leases are fully stopped and reconciled, so they do not block drain or smoke admission. They still serve two replay contracts: `acquire_worker` scans every lease by request ID to return an idempotent prior result, and late `release_worker` or observation replay resolves an exact lease ID rather than failing unknown-lease. Active and ambiguous states (`starting`, `active`, `observed_stopped`, `release_requested`, `dead_unreconciled`) must never be pruned.

The safe mechanical shape is to retain every non-quiescent lease plus a bounded newest tail of quiescent leases ordered by `quiescent_monotonic` with insertion order as the deterministic tiebreaker, pruning only at the single `_locked_state.save()` durable-write choke point. `quiescent_monotonic` is set on every transition to quiescent. `worker_lease_health` would then report the retained tail.

Unresolved blocker: no evidence yet defines the replay window or a justified retention count, and an unexplained hardcoded cap would recreate scarcity-shaped policy. Next check: observe the maximum legitimate delay between initial release and duplicate acquire/release/observation replays, then put the chosen retention policy in configuration with its rationale and qualify that active/reconciliation evidence is never removed.
