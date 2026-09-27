---
status: green
revised_at: "2026-09-27T12:38:25+10:00"
---

The workstation is `DDRiver`, an AMD Ryzen AI MAX+ 395 with Radeon 8060S (Strix Halo), 128 GiB unified physical memory and a GNOME desktop. Live inspection on 2026-09-27 reports Ubuntu 24.04.5 LTS and kernel 7.0.0-31-generic. David's desktop and personal work outrank autonomous agents.

**Memory is one pool.** GPU and ordinary host allocations share RAM. `memory.physical_bytes()` totals online memory blocks (137.4 decimal GB, approximately 128 GiB); `MemTotal` excludes boot reservations. The ledger and CLI use decimal GB. The dashboard retains its five-part donut and converts to GiB while labelling values GB. MemAvailable is labelled Free. Its CointOS total now comes from cgroup charges for Lemonade and live CointOS units; configured model sizes and snapshot bytes retain the weights/KV/saved-context proportions inside that measured total. Operating System is physical minus MemAvailable minus measured CointOS. This is deliberately approximate because cgroup charges and MemAvailable treat reclaimable/shared memory differently.

**Measurements.**
- `MemAvailable` in `/proc/meminfo` and PSI `full avg10` in `/proc/pressure/memory` drive workstation headroom and distress.
- `mem_info_gtt_used` under `/sys/class/drm/card*/device/` reports GPU use; the observed value with both configured models idle was about 46.9 decimal GB. `mem_info_gtt_total` reports a 64 GiB domain, not a proven allocation ceiling.
- `/proc/swaps` currently reports an 8 GiB swap file; swap in use is diagnostic, not a stop threshold.
- Lemonade is in `inference.slice`. Its current allowance reported by the backend is 77.3 decimal GB. Headroom is the smaller of available RAM minus reserve and server allowance minus anonymous/shared memory.

**Measuring everything outside CointOS.** Lemonade counts with CointOS. `memory.cointos_bytes` adds the `memory.current` charges for `inference.slice` and sibling user units matching `cointos*.service`, which includes the daemon, Coin and live agents. The dashboard subtracts that approximate CointOS charge from physical minus MemAvailable and clamps it at zero. It does not need privileged per-process DRM data. In a live post-restart sample, 137.4 decimal GB physical, 78.2 GB available and 32.5 GB charged to CointOS rendered as about 24.8 GiB for everything else. This is close-enough presentation accounting rather than a resource-control invariant; the guard remains based on MemAvailable and the Lemonade budget.

**Governing limits** come from `config/cointos.json`, not this leaf: currently a 24 decimal GB reserve, PSI threshold 1.0, and 30 seconds of sustained distress. Negative headroom first makes snapshots give way and can block background work; sustained PSI distress stops background agents and unloads the work model. There is no 2 GB swap-use limit.

**Earlier observations, not repeated load tests:** approximately 100 GiB was reported allocatable to the GPU; two 131,072-token work-model lanes ran without pressure, whereas loading three caused pressure. Treat these as shape-selection evidence, not guaranteed capacity. Recheck after hardware, kernel, driver or model-shape changes.
