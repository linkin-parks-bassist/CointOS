---
status: green
revised_at: "2026-10-19T14:13:44+11:00"
---

The workstation is `DDRiver`, an AMD Ryzen AI MAX+ 395 with Radeon 8060S (Strix Halo), 128 GiB unified physical memory and a GNOME desktop. Live inspection on 2026-09-27 reports Ubuntu 24.04.5 LTS and kernel 7.0.0-34-generic. David's desktop and personal work outrank autonomous agents.

**Memory is one pool.** GPU and ordinary host allocations share RAM. `memory.physical_bytes()` totals online memory blocks (137.4 decimal GB, approximately 128 GiB); `MemTotal` excludes boot reservations. The ledger and CLI use decimal GB. The dashboard uses a five-part memory bar and uses the ordinary RAM convention: configured weights and KV capacity stay as authored, byte counters are divided by 2³⁰, and all values are labelled GB. Model and snapshot categories are not scaled. MemAvailable includes reclaimable file-backed weights, whereas Gufo's anonymous weights already reduce it. The dashboard subtracts non-reclaimable loaded weights, KV and snapshots from non-reclaimable use to estimate Operating System; Free is the remaining physical partition.

**Measurements.**
- `MemAvailable` in `/proc/meminfo` and PSI `full avg10` in `/proc/pressure/memory` drive workstation headroom and distress.
- `mem_info_gtt_used` under `/sys/class/drm/card*/device/` reports GPU use; the observed value with both configured models idle was about 46.9 decimal GB. `mem_info_gtt_total` reports a 64 GiB domain, not a proven allocation ceiling.
- `/proc/swaps` currently reports an 8 GiB swap file; swap in use is diagnostic, not a stop threshold.
- Selected Gufo runs in its own scope with no Lemonade allowance; headroom is available RAM minus reserve. Earlier Lemonade inference.slice reported a 77.3 GB allowance and also considered allowance minus anonymous/shared memory.
- Earlier Lemonade work-model loads drove PSI `full avg10` to about 6 for roughly 20 seconds despite ample memory; recheck the selected backend rather than assuming the same load transient.

**Measuring everything outside CointOS.** model_memory marks selected Gufo weights non-reclaimable and llama's mapped weights reclaimable. Keep their authored sizes; subtract anonymous weights before attributing remaining used RAM to other/system, avoiding a second weight charge. Small daemon/Coin/agent allocations and configured-versus-resident estimation differences remain in that segment. A live Gufo inspection finds 17,145,856 KiB of its 17,147,636 KiB main anonymous weight mapping backed by transparent huge pages (about 99.99%), with zero native process swap; missing huge-page coverage does not explain the measured speed. The guard independently uses MemAvailable and any backend budget.

**Power measurement.** Reviewer sampling found AC and performance profile/governor/energy preference, with zero native swap and memory PSI. This does not establish a power bottleneck. Measure sysfs GPU clocks, temperature and power alongside matched decode steps before changing host policy.

**Governing limits** live in `config/cointos.json` under `memory`: the workstation reserve (`reserve_gb`), the RAM snapshot-cache budget (`snapshots_gb`; cold caches spill to the bounded disk tier), the PSI threshold (`max_psi`, raised to 1.5 at the user's request because pressure between 1.0 and 1.5 produced only nuisance alerts) and sustained distress (`distress_seconds`). The one threshold drives both the self-check alert and the guard. Snapshots give way first; sustained PSI stops background agents. Model unloading requires headroom still negative after shedding. Swap use is diagnostic.

**Earlier observations, not repeated load tests:** approximately 100 GiB was reported allocatable to the GPU; two 131,072-token work-model lanes ran without pressure, whereas loading three caused pressure. Treat these as shape-selection evidence, not guaranteed capacity. Recheck after hardware, kernel, driver or model-shape changes.
