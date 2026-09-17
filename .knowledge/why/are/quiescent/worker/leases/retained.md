---
status: "unverified"
created_at: "2026-09-17T20:30:41+10:00"
scope: "local"
source: "installed state/watchdog.json last_worker_lease_health after live watchdog tick 2026-09-17"
---

Installed watchdog worker_lease_health first reported 2,084 quiescent leases in generation 3 with mode open on 2026-09-17. Current knowledge does not establish whether terminal worker leases are deliberately retained as bounded audit history or accumulate without compaction. Blocker: retention and pruning ownership in workload_control has not been mapped. Next check: inspect the release/observation state transitions and every reader of terminal leases, then identify whether a bounded archive or deletion rule is safe.
