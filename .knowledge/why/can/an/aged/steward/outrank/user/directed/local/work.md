---
status: "unresolved"
created_at: "2026-09-17T21:11:44+10:00"
scope: "project local"
source: "ecosystem/scheduler.py, ecosystem/inference_capacity.py, ecosystem/cli.py, ecosystem/executor.py and all production enqueue_task call sites; tasks task-befb283c26344463 and task-d6d9e2b8eb3f4b25; installed queue observation 2026-09-17"
checked_at: "2026-09-17T21:54:00+10:00"
blocker: "The recognized user-directed creation origins are mapped but not yet stamped into durable jobs or consumed by scheduler.priority."
next_check: "Implement enqueue-time derivation for local-cli and authenticated Telegram contact_requested origins, consume only recognized durable origin values in scheduler.priority, then live-qualify against an aged Steward while confirming coin and sole-survivor bands remain higher."
updated_at: "2026-09-17T21:53:35+10:00"
---

A manually requested local mapper job can be overtaken by older periodic Steward work because the durable job scheduler does not classify the manual request as user-driven. `scheduler.priority(job, scheduling, now)` calls `effective_priority` with role, execution profile, authority profile, and age, but does not pass user-directed provenance. `effective_priority` enters the `user_driven` band only when its operator-session boolean is true; otherwise unknown roles such as mapper and Steward use the default role priority of 250 and age within the default band. In the live queue an older Steward reached 253 while the requested mapper remained 250, so the periodic review was repeatedly selected first.

Read-only mapper `task-befb283c26344463` traced manual creation through scheduling. `cli.enqueue_task` durably stores source, role, creation time, authority profile, and workload class, but not user-directed provenance. `cli.prepare_next` and `scheduler.choose` both use `scheduler.priority`; its `effective_priority` call is the smallest scheduling seam.

Read-only mapper `task-d6d9e2b8eb3f4b25` mapped all five production enqueue owners. Local CLI and authenticated Telegram/control task creation are user-directed. Watchdog Steward review, independent verification children, and resource-emergency Sole Survivor creation are not ordinary user-directed origins and already carry distinct authority/source data. All converge on the job-record assembly in `cli.enqueue_task`. Direct installed-coordinator dispatch intentionally uses the local-cli entry identity. The existing free-form source must not itself become a priority value, and no caller should supply a priority number or user-directed boolean.

The narrow implementation is to derive a recognized durable origin inside `cli.enqueue_task`: exact `local-cli` means local operator; a syntactically valid `telegram:<user-id>` combined with intake-derived `contact_requested` authority means authenticated Telegram direction; every other source yields no user-directed origin. `scheduler.priority` should map only those recognized stored origin values to the existing user-driven band. Coin and Sole Survivor authority bands remain higher. Periodic Steward, verification, recovery, malformed, unknown, and legacy records remain in their existing bands.

A narrow acceptance check compares an aged periodic Steward, a fresh recognized local or Telegram job, and an otherwise identical unknown-origin negative control. Only the recognized job enters the user-driven band and outranks the Steward; coin and Sole Survivor still outrank it.
