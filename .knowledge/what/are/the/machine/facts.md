---
status: green
revised_at: "2026-09-27T12:48:48+10:00"
---

The workstation is `DDRiver`, an AMD Ryzen AI MAX+ 395 with Radeon 8060S (Strix Halo), 128 GiB unified physical memory and a GNOME desktop. Live inspection on 2026-09-27 reports Ubuntu 24.04.5 LTS and kernel 7.0.0-31-generic. David's desktop and personal work outrank autonomous agents.

**Memory is one pool.** GPU and ordinary host allocations share RAM. `memory.physical_bytes()` totals online memory blocks (137.4 decimal GB, approximately 128 GiB); `MemTotal` excludes boot reservations. The ledger and CLI use decimal GB. The dashboard retains its five-part donut and uses the ordinary RAM convention: configured weights and KV capacity stay as authored, byte counters are divided by 2³⁰, and all values are labelled GB. Model and snapshot categories are not scaled. MemAvailable includes reclaimable model-weight pages, so the dashboard uses it to calculate non-reclaimable use rather than labelling it Free; Operating System is that use minus KV and snapshots, and Free is the remaining physical partition.

**Measurements.**
- `MemAvailable` in `/proc/meminfo` and PSI `full avg10` in `/proc/pressure/memory` drive workstation headroom and distress.
- `mem_info_gtt_used` under `/sys/class/drm/card*/device/` reports GPU use; the observed value with both configured models idle was about 46.9 decimal GB. `mem_info_gtt_total` reports a 64 GiB domain, not a proven allocation ceiling.
- `/proc/swaps` currently reports an 8 GiB swap file; swap in use is diagnostic, not a stop threshold.
- Lemonade is in `inference.slice`. Its current allowance reported by the backend is 77.3 decimal GB. Headroom is the smaller of available RAM minus reserve and server allowance minus anonymous/shared memory.

**Measuring everything outside CointOS.** The dashboard estimates other/system allocation as physical minus MemAvailable, configured KV capacity and measured in-memory snapshots. Model weights are kept as their configured size because their reclaimable file-backed pages are already included in MemAvailable. Small daemon, Coin and agent allocations remain in the other/system segment; this is the accepted close-enough error. A checked sample with both models loaded rendered about 20.4 GB weights, 25.6 GB KV, 7.8 GB saved contexts, 20.3 GB other/system and 53.9 GB free/reclaimable remainder. The resource guard remains based on MemAvailable and the Lemonade budget.

**Governing limits** come from `config/cointos.json`, not this leaf: currently a 24 decimal GB reserve, PSI threshold 1.0, and 30 seconds of sustained distress. Negative headroom first makes snapshots give way and can block background work; sustained PSI distress stops background agents and unloads the work model. There is no 2 GB swap-use limit.

**Earlier observations, not repeated load tests:** approximately 100 GiB was reported allocatable to the GPU; two 131,072-token work-model lanes ran without pressure, whereas loading three caused pressure. Treat these as shape-selection evidence, not guaranteed capacity. Recheck after hardware, kernel, driver or model-shape changes.
