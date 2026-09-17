---
status: "unverified"
created_at: "2026-09-17T16:31:05+10:00"
scope: "local"
source: "installed watchdog state after task-f37644773fa62fbd implementation 2026-09-17"
updated_at: "2026-09-17T20:31:08+10:00"
---

CointOS requires a mandatory periodic higher-order sanity pass across every durable queue and ownership system. Local state-machine validity is insufficient: the pass must ask whether accepted work is making progress, whether logical ownership agrees with live processes/backend capacity, whether already-visible or obsolete work still consumes scarce execution, whether newer high-priority work is trapped behind stale work, and whether code/config/service generations agree.

The pass should call subsystem-owned reconcilers rather than duplicate their transition logic, then evaluate cross-system invariants over control turns, managed jobs, native inference runs, worker leases, inference leases/proxy credentials, operator sessions, notifications, and service generation. Safe repairs include recovering dead owners, releasing proven ghosts, rescheduling retained work, and retiring execution that is already semantically satisfied. Unknown occupancy or ambiguous delivery must be retained and escalated, not guessed away.

A reconciler designed for service-start recovery must distinguish dead ownership from concurrent inspection. `executor.recover_abandoned_jobs()` is also called by the live periodic watchdog, so it must test `_process_alive(job)` before cancelling an inference lease or stopping a runner process group. The former ordering performed destructive cleanup first and killed a healthy observable Qwen worker on three consecutive watchdog ticks. The installed repair moves the liveness guard ahead of abandoned-runner cleanup. Live qualification manually invoked `agent-watchdog.service` during job `task-3193bb5b31014084`; the job retained the same PID, inference lease, and OpenCode session.

Every pass must persist a compact health snapshot with observations, repairs, unresolved incidents, and the next check. Repeated unresolved incidents should become visible operator incidents rather than endless hot retries or silent queueing. High-priority Cointelprofessional/user work trapped behind a non-resource controller limit is itself unhealthy even when every individual record is schema-valid.

Wired so far: `ecosystem/watchdog.py::tick` calls `control_turns.recover_interrupted()` each tick and persists its integer result as `last_control_turn_recovery`, then calls `control_turns.observe_head()` and persists the result as `last_control_turn_head`. `observe_head` is a pure read-only observation using the exact `_reserve_eligible` predicate shared with `reserve_next`. `tick` calls `executor.recover_abandoned_jobs()` and persists `last_managed_job_recovery`; the executor preserves every live runner before abandoned-owner cleanup. It calls `inference_proxy.reconcile_available_capacity(cli.ROOT)` and persists `last_inference_capacity_reconciliation`. Deterministic findings no longer bypass `steward_review_seconds`: reconciliation and finding collection still run every tick, while qualitative Steward jobs enqueue only when the configured review interval is due.

Worker-lease aggregate health is now wired. `workload_control.worker_lease_health(root)` reads `state/workload-control.json` through `_read_state` without creating a lock or mutating state and returns mode, generation, and exact lease counts grouped by state. `watchdog.tick` calls it once and persists `last_worker_lease_health` on both state-write paths. Source compilation passes. An installed manual watchdog tick persisted `{"mode": "open", "generation": 3, "lease_counts": {"quiescent": 2084}}`. The unexpectedly large terminal count is separately unresolved at `why/are/quiescent/worker/leases/retained.md`; the observer reports it without inferring cleanup policy.

Remaining work: add notification and service-generation observations, define the common subsystem result schema, and make repeated unresolved incidents visible operator incidents without inventing duplicate transitions.
