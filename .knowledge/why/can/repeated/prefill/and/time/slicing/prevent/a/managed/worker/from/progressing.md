---
status: "unresolved"
created_at: "2026-09-17T13:37:35+10:00"
scope: "project local"
source: "task-6827e1cc36494a7b durable job record and coordinator observation 2026-09-17"
checked_at: "2026-09-17T13:50:00+10:00"
blocker: "Scheduler charges repeated retained-session prefill against each fairness slice and no progress-aware exemption exists."
next_check: "Inspect time-slice start and available prefill/first-token progress signals in executor and observable OpenCode state."
updated_at: "2026-09-17T13:39:34+10:00"
---

A managed local worker can currently make no forward progress when its initial OpenCode session prefill consumes nearly the entire work time slice. The scheduler preempts it because other work is waiting, then resumes the same session and pays the large prefill cost again. `ReservePolicyDeduplicator` was dispatched seven times over about 33 minutes, accumulated only about 178 seconds of actual run time, produced about 240 KiB of repeated output, and made no source edits before operator cancellation. Its last recorded reason was `300-second time slice expired while other work is waiting`.

This is a scheduler livelock, not task complexity or model failure. A resumed managed session must receive enough uninterrupted execution to get beyond its retained-context prefill and perform useful work. Fairness slicing should account for prefill/recovery cost or preserve a warm backend/session so repeated dispatch cannot reset progress indefinitely.

Installed backend-instance reconciliation subsequently closed the cancelled job as `cancelled` and released its worker and inference allocations. That cleanup confirms the lifecycle backstop but does not resolve the progress livelock.

Blocker: the correct accounting mechanism has not been selected. Candidate fixes include charging prefill outside the productive time slice, extending a resumed slice based on measured prefill, or suppressing fairness preemption until the first post-resume progress boundary.

Next check: inspect where the executor starts the 300-second slice relative to OpenCode session resume and whether observable backend state exposes prefill completion or first generated token.
