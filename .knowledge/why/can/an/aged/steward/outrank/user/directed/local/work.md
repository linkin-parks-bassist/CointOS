---
status: "unverified"
created_at: "2026-09-17T21:11:44+10:00"
scope: "project local"
source: "ecosystem/cli.py and scheduler.py; mapper tasks task-befb283c26344463 and task-d6d9e2b8eb3f4b25; installed task-b27cce9dfd664d16 scheduling observation 2026-09-17"
checked_at: "2026-09-17T22:24:00+10:00"
review_when: "Recheck when task creation channels, durable origin fields, or scheduling bands change; live-observe the next Telegram-created deep task."
updated_at: "2026-09-17T22:24:12+10:00"
---

A manually requested local mapper job was previously overtaken by older periodic Steward work because the durable job scheduler did not classify the manual request as user-driven. `scheduler.priority(job, scheduling, now)` called `effective_priority` without user-directed provenance, so unknown roles used default priority 250 and aged periodic work could reach 253.

Two read-only mappers traced the scheduling path and all production enqueue owners. Local CLI and authenticated Telegram/control task creation are user-directed. Watchdog Steward review, independent verification children, and resource-emergency Sole Survivor creation are not ordinary user-directed origins and already carry distinct authority/source data. All converge on the job-record assembly in `cli.enqueue_task`.

The installed implementation derives durable provenance inside that single funnel without accepting a caller-supplied priority number or boolean. Exact source `local-cli` maps to `local_operator`. A syntactically valid `telegram:<decimal-user-id>` maps to `telegram_contact` only when intake-derived authority is exactly `contact_requested`. All other, malformed, legacy, watchdog, verification, and recovery sources omit the field. Omission preserves Sole Survivor's strict exact-field descriptor validation.

`scheduler.priority` passes the existing operator-session boolean to `effective_priority` only when the stored value is exactly one of those two recognized origins. Direct checks produced Sole Survivor 1000, Coin 900, recognized local and Telegram 850, an aged default Steward 253, and unknown origin 250. Thus Coin and Sole Survivor remain higher while user-directed work outranks background work.

Installed live qualification created task `task-b27cce9dfd664d16` through the coordinator's local enqueue path. Its durable record contains `source: local-cli` and `user_directed_origin: local_operator`; its scheduling reason scored `85000065.4`, proving the live scheduler used the user-driven band rather than the former default 250 band. The Telegram derivation has direct checks but awaits observation on the next genuine Telegram-created deep task.
