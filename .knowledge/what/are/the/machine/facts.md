---
status: green
revised_at: "2026-09-27T12:19:46+10:00"
---

The workstation is `DDRiver`, an AMD Ryzen AI MAX+ 395 with Radeon 8060S (Strix Halo), 128 GiB unified physical memory and a GNOME desktop. Live inspection on 2026-09-27 reports Ubuntu 24.04.5 LTS and kernel 7.0.0-31-generic. David's desktop and personal work outrank autonomous agents.

**Memory is one pool.** GPU and ordinary host allocations share RAM. `memory.physical_bytes()` totals online memory blocks (137.4 decimal GB, approximately 128 GiB); `MemTotal` excludes boot reservations. The ledger and CLI use decimal GB. The dashboard converts and labels memory values in GiB. It shows MemAvailable versus physical memory unavailable to that measure (in use/reserved), not separate measured OS/model/KV allocations. Saved-context file bytes are separate because file length is not resident memory.

**Measurements.**
- `MemAvailable` in `/proc/meminfo` and PSI `full avg10` in `/proc/pressure/memory` drive workstation headroom and distress.
- `mem_info_gtt_used` under `/sys/class/drm/card*/device/` reports GPU use; the observed value with both configured models idle was about 46.9 decimal GB. `mem_info_gtt_total` reports a 64 GiB domain, not a proven allocation ceiling.
- `/proc/swaps` currently reports an 8 GiB swap file; swap in use is diagnostic, not a stop threshold.
- Lemonade is in `inference.slice`. Its current allowance reported by the backend is 77.3 decimal GB. Headroom is the smaller of available RAM minus reserve and server allowance minus anonymous/shared memory.

**Governing limits** come from `config/cointos.json`, not this leaf: currently a 24 decimal GB reserve, PSI threshold 1.0, and 30 seconds of sustained distress. Negative headroom first makes snapshots give way and can block background work; sustained PSI distress stops background agents and unloads the work model. There is no 2 GB swap-use limit.

**Earlier observations, not repeated load tests:** approximately 100 GiB was reported allocatable to the GPU; two 131,072-token work-model lanes ran without pressure, whereas loading three caused pressure. Treat these as shape-selection evidence, not guaranteed capacity. Recheck after hardware, kernel, driver or model-shape changes.
