---
status: "unresolved"
created_at: "2026-09-17T16:31:05+10:00"
scope: "local"
source: "installed watchdog qualification; mapper tasks task-b27cce9dfd664d16 and task-9c1195d706e64c88; live systemctl show 2026-09-17"
updated_at: "2026-09-17T23:27:21+10:00"
blocker: "Post-swap generation identity and watchdog comparison are designed but not implemented."
next_check: "Write an atomic post-swap generation stamp with boot identity and monotonic completion time, observe each long-running unit's ExecStart and ExecMainStartTimestampMonotonic, persist the compact result, then live-qualify after a whole-system restart."
---

CointOS requires a mandatory periodic higher-order sanity pass across every durable queue and ownership system. Local state-machine validity is insufficient: the pass must ask whether accepted work is making progress, whether logical ownership agrees with live processes/backend capacity, whether already-visible or obsolete work still consumes scarce execution, whether newer high-priority work is trapped behind stale work, and whether code/config/service generations agree.

The pass should call subsystem-owned reconcilers rather than duplicate their transition logic, then evaluate cross-system invariants over control turns, managed jobs, native inference runs, worker leases, inference leases/proxy credentials, operator sessions, notifications, and service generation. Safe repairs include recovering dead owners, releasing proven ghosts, rescheduling retained work, and retiring execution that is already semantically satisfied. Unknown occupancy or ambiguous delivery must be retained and escalated, not guessed away.

A reconciler designed for service-start recovery must distinguish dead ownership from concurrent inspection. `executor.recover_abandoned_jobs()` is also called by the live periodic watchdog, so it must test `_process_alive(job)` before cancelling an inference lease or stopping a runner process group. The former ordering killed a healthy observable Qwen worker on three consecutive ticks. The installed repair preserves live runners; manual qualification retained the same PID, inference lease, and OpenCode session.

Every pass must persist a compact health snapshot with observations, repairs, unresolved incidents, and the next check. Repeated unresolved incidents should become visible operator incidents rather than endless hot retries or silent queueing. High-priority Cointelprofessional/user work trapped behind a non-resource controller limit is itself unhealthy even when every individual record is schema-valid.

Wired so far: `watchdog.tick` persists control-turn recovery/head, managed-job recovery, native and operator recovery, inference-capacity reconciliation, worker-lease health, and notification health on both state-write paths. Subsystem owners perform their own transitions. Deterministic finding collection runs every tick while qualitative Steward enqueue remains governed by `steward_review_seconds`.

`workload_control.worker_lease_health(root)` is read-only and returns mode, generation, and exact lease counts grouped by state. Its first installed snapshot exposed 2,084 quiescent leases; retention policy is unresolved at `why/are/quiescent/worker/leases/retained.md`.

`outbox.delivery_health()` is read-only and returns six state counts plus `oldest_pending_updated_at`; watchdog persists it as `last_notification_health`. Tracing its first stuck record repaired cancelled-dependency release, default managed notification inference, and terminal-response cleanup evidence; the retained notification then delivered. Owner: `why/did/cointos/notifications/fail/to/deliver.md`.

Service-generation mapper `task-b27cce9dfd664d16` established that `scripts/cointos-system` owns the complete generation membership: six long-running services, three triggers, and two triggered oneshots. Active state proves availability but not code/config identity, and oneshots may legitimately be transiently active.

Identity mapper `task-9c1195d706e64c88` found that `scripts/install-cointos` already atomically swaps `.cointos-install.json` after payload files, but its `installed_at` timestamp is captured before the swap. The installer rewrites shipped systemd units from source-checkout paths to `~/.CointOS`, but does not install/enable them; live truth therefore requires each unit's actual `ExecStart`, not only `FragmentPath`. A live `systemctl --user show` confirmed the running control worker executes `/home/david/.CointOS/scripts/control-worker` from a fragment under `~/.config/systemd/user`.

The minimal proof is an atomic post-swap generation stamp under `~/.CointOS` plus per-unit systemd identity. To avoid wall-clock parsing and survive reboot correctly, the stamp should contain schema version, source revision, current boot ID, and completion monotonic microseconds. For the same boot, a running unit is current only when its `ExecMainStartTimestampMonotonic` is at or after the stamp and `ExecStart` is under the installed prefix. Across a later boot, no pre-install process can survive, so installed-prefix execution plus active state is sufficient. Missing/unreadable stamp or failed systemd observation is unavailable, never guessed current. Source-prefix execution or a same-boot start before the stamp is a mismatch requiring the whole-system restart boundary, never an individual-unit restart.

Remaining work: implement and persist service-generation health, define the common subsystem result schema, make repeated unresolved incidents visible operator incidents, and consume notification health in findings rather than the dead `outbox.delivery_failed` event name.
