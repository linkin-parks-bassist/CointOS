---
status: green
revised_at: "2026-09-26T02:14:10+10:00"
---

A physical backend growth can create a runnable sequence while queued jobs remain unchanged. Enqueue wakes dispatch only when a job is created; the ecosystem fallback timer is five minutes. A CointOS-only two-job probe exposed the gap: automatic 1→2 growth succeeded, but the queued sibling started only after an explicit ecosystem service wake.

The installed repair makes `backend_profiles.finish_transition()` persist `backend_profile_dispatch_pending` with the exact transition ID on verified reconfiguration or rollback. `backend_profile_scheduler.reconcile_once()` writes the existing `agent-enqueue.wakeup` path through `cli.wake_dispatch(root)` and clears only the matching pending marker under the capacity lock. An I/O failure leaves the marker for a later timer retry; fenced recovery takes precedence. Read-only `cointos-profile plan` reports `dispatch_wakeup_required` if the marker remains. The installed automatic idle 2→1 shrink triggered `agent-ecosystem.path` immediately and left no pending marker, no fence and no failed service. A live automatic growth with this repaired generation has not yet been observed. Requalify after changing the transition, timer, path trigger or lane dispatcher.
