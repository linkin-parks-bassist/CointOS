---
status: "unverified"
created_at: "2026-09-17T12:52:51+10:00"
scope: "project local"
source: "David explicit Strix Halo hardware capability; models.py and inference_capacity.py repair plus installed live snapshot 2026-09-17"
---

On this 128 GB unified-memory Strix Halo host, David confirms that 100 GiB is currently available at the hardware level for GPU allocation. The configured `physical_capacity.gtt_limit_bytes = 107374182400` is the qualified allocation boundary.

`/sys/class/drm/card*/device/mem_info_gtt_total` currently reports 64 GiB, but that value describes one amdgpu kernel GTT reporting domain. It is not the machine's physical GPU-allocation ceiling. Treating it as a cap caused `models.snapshot()` and `inference_capacity.resource_envelope()` to compute `min(64 GiB, 100 GiB)`, silently discarding 36 GiB of real capability and repeatedly teaching agents that the configured limit was unsafe.

The repaired contract separates capacity from observation. Configured `gtt_limit_bytes` supplies the qualified capacity boundary. Fresh `mem_info_gtt_used` remains a live occupancy/pressure signal. `mem_info_gtt_total` remains informational and may be recorded with its amdgpu sysfs provenance, but its presence, freshness, or numeric value does not lower or invalidate admission capacity.

Installed live evidence after the repair reported the sysfs domain as 64 GiB, current GTT use as 33.553 GiB, the admission boundary as 100 GiB, and the resource envelope as verified. Existing inference-capacity, model-admission, resource-control, and resident-pool checks passed after their stale total-as-cap expectations were corrected. Recheck if the hardware allocation configuration, kernel memory interface semantics, or host changes.
