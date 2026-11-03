---
status: green
revised_at: "2026-11-03T18:18:44+11:00"
---

The workstation's unified RAM is one pool. `memory.py` derives physical headroom from `MemAvailable`, the workstation reserve and any inference-slice allowance. Gufo is charged through host memory. The guard uses physical headroom and PSI; swap occupancy alone is diagnostic. Sustained distress or negative headroom after cache shedding stops background agents uncharged. Unloading requires headroom still negative; recovery waits for configured calm time.

`capacity.py` owns unspent admission capacity. Each active run holds its full configured process cap, converting systemd's binary G units to decimal GB, plus the runner's state-and-scratch claim until native initialization. The full cap is deliberately conservative. Spawning, native allocation and disposable caches use this same budget. Native initialization spends its own state claim while preserving other claims. Unknown capacity refuses new admission. Pending saves and copy-backs stay reserved through fresh measurements.

A new agent needs about 20 GB: the 8.59 GB process cap plus the 11.35 GB native state. After the 24 GB reserve there is often room for only one agent, so the order `spawner.next_task` starts work in decides throughput. Other workstation processes, such as a browser tab holding 14 GB, take directly from that room.

`capacity.conversation_cache_gb` releases process-cap claims for a Coin conversation's saves and resident state, because a waiting user pays for each skipped save in rereads, and the guard sheds caches first. why/does/coin/reread/its/whole/context/on/every/model/request.md owns the cause. A save that doesn't fit is skipped, not failed: the run continues and its context is reread if the lane switches away. `snapshots.skipped` logs `snapshot skipped` once per owner until one of its saves succeeds.

Unresolved defect: a task's resident admission can fail after its run was admitted. When `MemAvailable` drifts below what `lanes.switch` needs, the thought raises MemoryError after `timeouts.server_seconds`, and repeated failures end the run. Seen on 10-29, 10-30, 11-02 and 11-03 (worker-12ba47, 12:35-12:40). Next check: make an admitted run wait for capacity instead of failing.

Native persistence captures device state before writing its RAM file, so admission covers both the estimated file and a full native state claim. An unmeasured file uses the runner's state estimate. RAM cache capacity bounds retained files. Retired files stay charged until physical deletion. Cleanup keeps filesystem deletion outside the state lock.

Native task state belongs to a running client or in-flight thought. Cleanup retires GPU states for tasks awaiting review or waiting without a run. Live clients keep state between tool calls; transcripts, sessions, budgets and persistence hints survive retirement. Hot switches never serialize live resident state.

The 24 GB reserve and 40/300 GB RAM/disk cache budgets come from the 2026-10-27 correction of repeated four-agent restarts and memory stops. Evidence: ~/.local/state/cointos/memory-admission-20261027/.
