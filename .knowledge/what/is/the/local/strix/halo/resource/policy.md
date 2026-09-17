---
status: "unverified"
created_at: "2026-09-15T22:09:16+10:00"
scope: "project local"
source: "David explicit abundance-first policy; live host observations; config/resource-policy.json and installed qualification through 2026-09-17"
updated_at: "2026-09-17T13:39:02+10:00"
---

This CointOS host is a Strix Halo machine with nominal 128 GB unified LPDDR5 memory. Linux has reported 134149070848 bytes (124.936 GiB) of physical RAM. David explicitly confirms that 100 GiB is available at the hardware level for GPU use; the configured 100 GiB GPU boundary represents that capability. A 64 GiB value observed through one amdgpu GTT sysfs domain is not evidence that hardware GPU allocation is capped at 64 GiB and must not reduce the 100 GiB ceiling. Fresh observations still govern current pressure and occupancy.

`config/resource-policy.json` now has one owner for physical byte reserves: `physical_capacity` defines `protected_host_bytes` (32 GiB), `coin_reserved_bytes` (8 GiB), `load_transient_bytes` (12 GiB), and `gtt_limit_bytes` (100 GiB). The inference-capacity loader merges those into its validated scheduling view. `inference_capacity` retains sequence, model-residency, lease, proxy, clock, and transport-related settings and no longer duplicates the four physical values. Installed inspection confirmed zero overlapping keys and unchanged resolved values.

Policy is abundance-first within measured boundaries. General agent work receives the largest useful verified context and output allowances; when backend and client support it, 32000 output tokens is the minimum ordinary-worker allowance. Allocate a fitting backend, reclaim idle lower-priority residency, or queue retained work rather than silently starving an agent. Small limits require a named workload reason and evidence that truncation cannot discard work. The fast-front 512-token allowance is a specialized latency response, not a worker precedent.

The three remaining memory margins protect the interactive desktop, control plane, and load transients. Their duplication is resolved, but their numeric rationale and combined effect still require measurement. They are safety margins, not a general reason to leave usable capacity idle or deny benign work. Reconcile observed availability automatically; ghosts, stale observations, conservative defaults, package versions, and unexplained constants must not become terminal gates.

Before changing a capacity ceiling, record its physical or workload rationale and recovery behavior in KT. Review at a glance against this machine profile: a general-worker allowance tiny relative to verified backend capacity is a defect even when tests prove enforcement.
