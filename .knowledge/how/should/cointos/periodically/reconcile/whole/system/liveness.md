---
status: "unverified"
created_at: "2026-09-17T16:31:05+10:00"
scope: "local"
source: "installed last_notification_health and live delivery qualification 2026-09-17"
updated_at: "2026-09-17T21:08:55+10:00"
---

CointOS requires a mandatory periodic higher-order sanity pass across every durable queue and ownership system. Local state-machine validity is insufficient: the pass must ask whether accepted work is making progress, whether logical ownership agrees with live processes/backend capacity, whether already-visible or obsolete work still consumes scarce execution, whether newer high-priority work is trapped behind stale work, and whether code/config/service generations agree.

The pass should call subsystem-owned reconcilers rather than duplicate their transition logic, then evaluate cross-system invariants over control turns, managed jobs, native inference runs, worker leases, inference leases/proxy credentials, operator sessions, notifications, and service generation. Safe repairs include recovering dead owners, releasing proven ghosts, rescheduling retained work, and retiring execution that is already semantically satisfied. Unknown occupancy or ambiguous delivery must be retained and escalated, not guessed away.

A reconciler designed for service-start recovery must distinguish dead ownership from concurrent inspection. `executor.recover_abandoned_jobs()` is also called by the live periodic watchdog, so it must test `_process_alive(job)` before cancelling an inference lease or stopping a runner process group. The former ordering killed a healthy observable Qwen worker on three consecutive ticks. The installed repair preserves live runners; manual qualification retained the same PID, inference lease, and OpenCode session.

Every pass must persist a compact health snapshot with observations, repairs, unresolved incidents, and the next check. Repeated unresolved incidents should become visible operator incidents rather than endless hot retries or silent queueing. High-priority Cointelprofessional/user work trapped behind a non-resource controller limit is itself unhealthy even when every individual record is schema-valid.

Wired so far: `watchdog.tick` persists control-turn recovery/head, managed-job recovery, native and operator recovery, inference-capacity reconciliation, worker-lease health, and notification health on both state-write paths. Subsystem owners perform their own transitions. Deterministic finding collection runs every tick while qualitative Steward enqueue remains governed by `steward_review_seconds`.

`workload_control.worker_lease_health(root)` is read-only and returns mode, generation, and exact lease counts grouped by state. Its first installed snapshot exposed 2,084 quiescent leases; retention policy is unresolved at `why/are/quiescent/worker/leases/retained.md`.

`outbox.delivery_health()` is read-only and returns six state counts plus `oldest_pending_updated_at`; watchdog persists it as `last_notification_health`. The first installed snapshot exposed 22 failed, one delivery-unknown, and one hours-old waiting notification. Tracing that record repaired cancelled-dependency release, default managed notification inference, and terminal-response cleanup evidence; the retained notification then delivered in one attempt. Owner: `why/did/cointos/notifications/fail/to/deliver.md`.

Remaining work: add service-generation observation, define the common subsystem result schema, and make repeated unresolved incidents visible operator incidents without inventing duplicate transitions. Notification findings should consume the state-based summary rather than the dead `outbox.delivery_failed` event name.
