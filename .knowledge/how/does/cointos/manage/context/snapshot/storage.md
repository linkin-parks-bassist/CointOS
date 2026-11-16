---
status: green
revised_at: "2026-11-16T19:29:44+11:00"
checked_at: '2026-11-17T07:40:24+11:00'
---

Snapshots are disposable performance hints, never task/conversation authority. A namespace rotation must retire the old tmpfs store after verifying no runner uses it; scanning only the new configured store cannot reclaim those orphan bytes. Coin profiles with retain_diagnostics=false save no checkpoints. Private user requests use ordinary owner-bound prefix/checkpoint reuse, but their binary KV files stay in tmpfs: no publication of private prefixes, disk spill or shutdown persistence. Private requests can restore an exact matching non-private cache; private-owned caches remain inaccessible to other owners. Memory pressure may discard these optional caches. Orphan reconciliation removes disabled-profile and unreachable-client caches; private restore/deduplication stays owner-bound. Private KV state survives tool/turn gaps for the live client process; PID/start/boot receipts establish its lifetime without transcript persistence. Startup retires unreachable caches; terminal tasks retain them while a run survives. Native execution residency has the client/run lifetime owned by how/does/gufo/select/resident/agent/state.md.

Reachability never ends Coin, user and shared conversations, and waiting tasks can wait indefinitely, so reconciliation also retires memory/disk caches whose `last_run` is older than memory.snapshot_idle_hours (36, user-requested). Saves, identical-bytes reuse, prefix retention and restores refresh `last_run`; transfers and pinned restore inputs wait for a later pass. Expiry costs only a reread.

Retirement separates logical removal from physical deletion. snapshot_cleanup owns per-format/tier canonical filename jobs in durable snapshot_garbage. Retired bytes remain charged through unlink/restart. Independent RAM/disk workers inventory/delete outside LOCK; SSD disposal never runs on the model worker. Inventory failure gates that tier; failed deletion retains charge/error for retry. Discovery rechecks ownership under LOCK. Saves reserve names, transfers retain ownership and restores pin inputs. Pending names cannot be reused. RAM restoration can proceed while its obsolete SSD copy deletes.

Replacement admission identifies same-owner/model/kind compatible superseded caches. Checkpoints supersede compatible suspensions; suspension preserves checkpoints; semantic/shared prefixes remain independent. Retire obsolete RAM first only when release can satisfy cache capacity and host headroom. Required RAM reclamation completes outside LOCK. Credit actual released bytes once, capped by measured headroom less unpublished saves/unspills. Pending transfers/deletions are not free. Retain old hints until success when both fit; failed pressure replacement can reread without losing history.

Disk admission waits for actual capacity. Ordinary lane work retains its RAM fallback while pending SSD cleanup could admit a spill. Copy-back publishes RAM eligibility without synchronously deleting SSD; cleanup owns deletion. Shutdown may wait outside LOCK for disk capacity.

Restoration tries compatible prefixes longest first; an admission-refused/invalid longer cache cannot hide a shorter one. Interrupted transfers choose the configured namespace and retain a regular copy matching recorded positive length, preferring RAM. Native restore validates bytes. Missing/partial/discarded/retired copies remain misses. Startup can synchronously remove a losing transfer copy, unlike ordinary retirement.

Admission prefers an idle llama slot's native byte count when held-token positions agree (server-build owner). Older servers use sample estimation: nearest larger context, upward scaling beyond range, fixed-state floor and upward rounding. Actual saves reconcile the estimate. Installed native first-save estimation uses the runner's state claim; capture also reserves a state claim for the GPU copy coexisting with the RAM file. Pending saves/copy-backs and active execution capacity stay protected across measurements. Non-native first saves remain unestimated. Eviction prefers inactive owners/recency; headroom shedding prefers shared starts/recency. RAM/disk budgets remain 40/300 GB.

Historical cleanup qualification found no cleanup errors, reclaimed 5.20 GB and preserved live sessions; severe-pressure resilience remains unproved. Evidence: workflow-observation-20261019/snapshot-cleanup-{verified.json,activation/recovery.json,live-summary.json} and snapshot-unlink-lock-stall.json.

Proof:

```bash
python3 -m unittest -q tests.test_snapshot_cleanup tests.test_snapshot_transfers tests.test_snapshots tests.test_snapshot_limit tests.test_backend_gufo tests.test_memory_and_checks tests.test_turns tests.test_scheduler tests.test_capacity
```
