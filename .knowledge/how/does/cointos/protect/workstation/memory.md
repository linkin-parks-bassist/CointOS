---
status: green
revised_at: "2026-11-17T12:09:27+11:00"
---

The workstation's unified RAM is one pool. `memory.py` derives physical headroom from `MemAvailable`, the `memory.reserve_gb` workstation reserve (12 GB) and any inference-slice allowance. Gufo and experimental Halogen use host accounting; Halogen subtracts its SVM-pinned 66.687678432 GB payload because MemAvailable still treats those weights as reclaimable. Lemonade's cgroup limit does not apply. how/to/integrate/halogen/with/cointos.md owns evidence. The guard uses physical headroom and PSI; swap occupancy alone is diagnostic. Sustained distress or negative headroom after cache shedding stops background agents uncharged. Unloading requires headroom still negative; recovery waits for configured calm time.

`capacity.py` owns unspent admission capacity. `MemAvailable` already counts what agent processes use now, so each active run holds only its room to grow (the user's choice, 2026-11-05). `capacity.observe`, run at each daemon memory measurement, reads every `cointos-agent-<id>.service` cgroup's anon+shmem and keeps its peak; a run holds min(cap, max(`agent_memory_gb`, peak) + `agent_margin_gb` 1.5) − current. In its first `agent_measure_grace_seconds` (60) it holds the 2.5 GB starting estimate; an unmeasurable run holds the full `agent_limit_gb` cap (8.59 GB, the systemd MemoryMax). Runs also hold the runner's state-and-scratch claim until native initialization. Spawning, native allocation and disposable caches use this budget. Unknown native capacity refuses admission. Pending saves and copy-backs stay reserved through fresh measurements.

Retained Gufo admission: 13.8 GB = 2.5 process + 11.35 native state; current llama slots are preallocated. Other workstation processes take directly from that room. Growth beyond a run's margin is caught by the guard and its hard cap, not by admission.

`capacity.conversation_cache_gb` releases agents' growth claims for a Coin conversation's saves and resident state, because a waiting user pays for each skipped save in rereads, and the guard sheds caches first. why/does/coin/reread/its/whole/context/on/every/model/request.md owns the cause. A save that doesn't fit is skipped, not failed; `snapshots.skipped` logs `snapshot skipped` once per owner until one succeeds.

Resident admission parks a thought as `waiting_for=memory` when headroom cannot cover its native state. It releases the lane/worker immediately, preserves the request and rejoins normal allocation when measured headroom returns. Capacity waiting is not reported as GPU starvation. Private client KV lifetime remains separate from serialized snapshot retention.

Persistence admission covers the RAM file plus any native capture claim. Supported idle llama slots report serialized bytes at the held-token position without KV cloning. Other runners retain sample/state estimates. RAM budgets bound retained files; retired bytes stay charged until deletion outside LOCK.

Native task state belongs to a running client or in-flight thought. Cleanup retires GPU states for tasks awaiting review or waiting without a run. Live clients keep state between tool calls; transcripts, sessions, budgets and persistence hints survive retirement. Hot switches never serialize live state to checkpoint files; experimental Halogen permits retained-cache recurrent-state copies.

The user set the 12 GB reserve on 2026-11-17: with Halogen resident, the previous 24 GB left headroom near zero, and ordinary desktop use made the guard unload Halogen about every five minutes. The 40/300 GB RAM/disk cache budgets come from the 2026-10-27 correction of repeated four-agent restarts and memory stops (~/.local/state/cointos/memory-admission-20261027/).
