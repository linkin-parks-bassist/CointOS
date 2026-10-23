---
status: green
revised_at: "2026-10-19T23:20:13+11:00"
---

Snapshots are disposable performance hints, never task/conversation authority. Startup retires unreachable caches; terminal tasks retain them while a run survives.

Installed retirement separates logical retirement from physical deletion. snapshot_cleanup owns per-format, per-tier, canonical filename jobs in durable snapshot_garbage. Retired bytes remain charged until actual unlink completes, including after restart. Independent RAM/disk workers inventory and delete outside LOCK; SSD disposal never runs on the model worker. A failed inventory gates allocations in that tier; failed deletion retains its charge and observable error for retry. Discovery rechecks file ownership under LOCK after scanning. Saves reserve names, transfers retain ownership through completion, and native restores pin their input files. Pending names cannot be reused. A RAM restore can proceed while its obsolete SSD copy is deleting.

Replacement admission identifies same-owner/model/kind token-compatible superseded caches. Checkpoints also supersede compatible suspensions; suspension preserves checkpoints, and semantic/shared prefixes remain independent. Retire obsolete RAM first only when its release can satisfy both cache capacity and host headroom. Required RAM reclamation completes outside LOCK before saving. Credit actual allocation release once, capped by fresh physical headroom less unpublished saves/unspills. Pending transfers/deletions are not free. Retain old hints until save succeeds when both fit; a failed pressure replacement can reread without losing history.

Disk admission stages eviction but waits for actual capacity before spilling. Ordinary lane work retains a usable RAM fallback while pending SSD cleanup could admit its spill later. Disk-to-RAM copy-back publishes RAM eligibility without synchronously unlinking the SSD source; cleanup owns that deletion. Machine shutdown can wait outside LOCK for disk cleanup before reserving each persistence transfer.

Installed restoration tries compatible prefixes longest first: an admission-refused or native-invalid longer cache cannot hide a shorter usable one. Interrupted transfer recovery chooses the configured model namespace and retains a regular copy matching recorded positive byte length, preferring RAM. Native restore still checks opaque validity. Missing/partial copies become misses; discarded/retired owners are never recovered. Startup recovery can still synchronously remove the losing transfer copy before serving; this is distinct from ordinary retirement.

Estimates use the nearest measured same-model context at least as large, preserve fixed overhead, scale upward above range, never fall below smaller measured files, round upward and reconcile actual saves. First saves remain unestimated. Other capacity eviction prefers inactive owners then recency; headroom shedding prefers shared starts then recency. RAM/disk budgets remain 40/300 GB.

Four timeout stacks identify the repaired snapshots.keep/drop → forget/os.remove path under LOCK (snapshot-unlink-lock-stall.json). Qualification passes 117 focused source/installed checks and 1,061 full source tests, with three native-only skips. Ten-module activation takes 4.42 seconds, preserving native/Coin and the three agents at the stop boundary, sessions/spend and configuration. An ordinary 237.94-second window has 120 successful responses, median 142.49/max 244.97 ms, no cleanup errors, and one 5.20 GB RAM retirement physically completes. I/O PSI peaks at only 0.18: severe-pressure resilience and natural fallback/recovery speedups remain unproved. Evidence: workflow-observation-20261019/snapshot-cleanup-{verified.json,activation/recovery.json,live-summary.json}.

Proof:

```bash
python3 -m unittest -q tests.test_snapshot_cleanup tests.test_snapshot_transfers tests.test_snapshots tests.test_snapshot_limit tests.test_backend_gufo tests.test_memory_and_checks tests.test_turns tests.test_scheduler
```
