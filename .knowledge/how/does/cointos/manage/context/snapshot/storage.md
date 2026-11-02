---
status: green
revised_at: "2026-10-27T08:59:35+11:00"
---

Snapshots are disposable performance hints, never task/conversation authority. Startup retires unreachable caches; terminal tasks retain them while a run survives. Native execution residency has the shorter run/thought lifetime owned by how/does/gufo/select/resident/agent/state.md.

Retirement separates logical removal from physical deletion. snapshot_cleanup owns per-format/tier canonical filename jobs in durable snapshot_garbage. Retired bytes remain charged through unlink/restart. Independent RAM/disk workers inventory/delete outside LOCK; SSD disposal never runs on the model worker. Inventory failure gates that tier; failed deletion retains charge/error for retry. Discovery rechecks ownership under LOCK. Saves reserve names, transfers retain ownership and restores pin inputs. Pending names cannot be reused. RAM restoration can proceed while its obsolete SSD copy deletes.

Replacement admission identifies same-owner/model/kind compatible superseded caches. Checkpoints supersede compatible suspensions; suspension preserves checkpoints; semantic/shared prefixes remain independent. Retire obsolete RAM first only when release can satisfy cache capacity and host headroom. Required RAM reclamation completes outside LOCK. Credit actual released bytes once, capped by measured headroom less unpublished saves/unspills. Pending transfers/deletions are not free. Retain old hints until success when both fit; failed pressure replacement can reread without losing history.

Disk admission waits for actual capacity. Ordinary lane work retains its RAM fallback while pending SSD cleanup could admit a spill. Copy-back publishes RAM eligibility without synchronously deleting SSD; cleanup owns deletion. Shutdown may wait outside LOCK for disk capacity.

Restoration tries compatible prefixes longest first; an admission-refused/invalid longer cache cannot hide a shorter one. Interrupted transfers choose the configured namespace and retain a regular copy matching recorded positive length, preferring RAM. Native restore validates bytes. Missing/partial/discarded/retired copies remain misses. Startup can synchronously remove a losing transfer copy, unlike ordinary retirement.

Estimates use nearest measured same-model context at least as large, preserve fixed overhead, scale upward beyond range, never undercut smaller measured files, round upward and reconcile actual saves. Installed native first-save estimation uses the runner's state claim; capture also reserves a state claim for the GPU copy coexisting with the RAM file. Pending saves/copy-backs and active execution capacity stay protected across measurements. Non-native first saves remain unestimated. Eviction prefers inactive owners/recency; headroom shedding prefers shared starts/recency. RAM/disk budgets remain 40/300 GB.

Historical cleanup qualification: 117 focused and 1,061 full source tests (three native-only skips); 4.42-second activation preserved native/Coin, three agents, sessions/spend/config. A 237.94-second observation had 120 API responses (median 142.49/max 244.97 ms), no cleanup errors and 5.20 GB physically reclaimed. I/O PSI peaked at 0.18; severe-pressure resilience/fallback speedups remain unproved. Evidence: workflow-observation-20261019/snapshot-cleanup-{verified.json,activation/recovery.json,live-summary.json} and snapshot-unlink-lock-stall.json.

Proof:

```bash
python3 -m unittest -q tests.test_snapshot_cleanup tests.test_snapshot_transfers tests.test_snapshots tests.test_snapshot_limit tests.test_backend_gufo tests.test_memory_and_checks tests.test_turns tests.test_scheduler tests.test_capacity
```
