---
status: "green"
revised_at: "2026-09-26T10:51:40+10:00"
---

The machine is host `DDRiver`: an AMD Strix Halo APU with 128 GB of unified memory, running Ubuntu with a GNOME desktop that David uses as his daily workstation.

**Memory is one pool.** GPU allocations and ordinary host memory come from the same 128 GB, so model weights and KV caches reduce what the desktop has.

- About 100 GiB can be allocated to the GPU.
- `mem_info_gtt_used` (under `/sys/class/drm/card*/device/`) measures GPU memory in use. `mem_info_gtt_total` reports a 64 GiB kernel reporting domain, which is not the allocation limit.
- With Qwen3.8-27B (262,144 total context) and Qwen3.5-4B loaded, GPU memory in use was about 46.5 GB, and `MemAvailable` was about 51–55 GB with a normal desktop session open.
- Swap is 7 GB.

**Desktop health** is read from `MemAvailable` in `/proc/meminfo` and memory pressure in `/proc/pressure/memory` (PSI). On unified memory these already include GPU use.

**Observed:**
- Qwen3.8 at 2 lanes of 131,072 tokens runs without memory pressure.
- Loading it with 3 such lanes caused memory pressure during load.

**Starting physical limits**, tuned from live observation:
- `MemAvailable` at least 24 GB;
- memory PSI `full avg10` at most 1.0;
- swap used at most 2 GB.
