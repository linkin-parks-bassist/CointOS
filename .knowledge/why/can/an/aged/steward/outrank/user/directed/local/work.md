---
status: "unresolved"
created_at: "2026-09-17T21:11:44+10:00"
scope: "project local"
source: "ecosystem/scheduler.py, ecosystem/inference_capacity.py, config/scheduling.json and installed queue observation 2026-09-17"
checked_at: "2026-09-17T21:11:44+10:00"
blocker: "The owning durable relationship between a local managed job and its initiating operator or user request has not yet been mapped."
next_check: "Trace manual dispatch creation through executor reservation, identify the smallest authoritative provenance field that survives restart, then wire scheduler priority from it and live-qualify against an aged Steward."
---

A manually requested local mapper job can be overtaken by older periodic Steward work because the durable job scheduler does not classify the manual request as user-driven. `scheduler.priority(job, scheduling, now)` calls `effective_priority` with role, execution profile, authority profile, and age, but does not pass authoritative operator-session state. `effective_priority` enters the `user_driven` band only when `operator_session=True`; otherwise unknown roles such as mapper and Steward use the default role priority of 250 and age within the default band. In the live queue an older Steward reached 253 while the requested mapper remained 250, so the periodic review was repeatedly selected first.

The fix must derive user-directed status from durable trusted state rather than accept a caller-supplied priority flag. User requests should enter the configured `user_driven` band, while periodic/background work remains in its role band and may be suspended for higher-priority active work.
