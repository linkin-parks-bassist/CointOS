---
status: "unverified"
created_at: "2026-09-15T22:09:16+10:00"
scope: "project local"
source: "config/resource-policy.json; ecosystem/models.py; ecosystem/inference_capacity.py; ecosystem/resource_control.py; task-4894b791ecbcbafc report 2026-09-17"
updated_at: "2026-09-17T14:59:53+10:00"
---

This CointOS host is a Strix Halo machine with nominal 128 GB unified LPDDR5 memory. Linux has reported 134149070848 bytes (124.936 GiB) of physical RAM. David explicitly confirms that 100 GiB is available at the hardware level for GPU use; the configured 100 GiB GPU boundary represents that capability. A 64 GiB value observed through one amdgpu GTT sysfs domain is not evidence that hardware GPU allocation is capped at 64 GiB and must not reduce the 100 GiB ceiling. Fresh observations still govern current pressure and occupancy.

`config/resource-policy.json` has one owner for physical byte reserves: `physical_capacity` defines `protected_host_bytes` (32 GiB), `coin_reserved_bytes` (8 GiB), `load_transient_bytes` (12 GiB), and `gtt_limit_bytes` (100 GiB). The inference-capacity loader merges those into its validated scheduling view. `inference_capacity` retains sequence, model-residency, lease, proxy, clock, and transport-related settings and no longer duplicates the four physical values. Installed inspection confirmed zero overlapping keys and unchanged resolved values.

The three reserves stack in live host admission. `models._model_route` compares protected host + coin reserve + unloaded-model bytes + load transient + incremental KV against available host memory. `inference_capacity.resource_envelope` subtracts protected host + coin reserve + load transient + active lease bytes + nonresident-model bytes from host headroom. `models.snapshot` computes the same host model headroom. Only load transient enters GTT admission; protected host and coin reserve are host-only. Load transient is omitted from KV-only headroom. `resource_control._preempt_leased_models_if_unprotected` also passes coin reserve as the required pressure-reclamation amount.

Both `models` routing and `inference_capacity` independently enforce the reserves in series for one executor admission. Raw reserve fields published in the models envelope and route echo are not read by production consumers; the route re-derives them from policy. `models.py` also emits a separate `model_bytes` exclusion that is arithmetically subsumed by the later host/GTT gates but preserves a distinct diagnostic reason.

Policy is abundance-first within measured boundaries. General agent work receives the largest useful verified context and output allowances; when backend and client support it, 32000 output tokens is the minimum ordinary-worker allowance. Allocate a fitting backend, reclaim idle lower-priority residency, or queue retained work rather than silently starving an agent. Small limits require a named workload reason and evidence that truncation cannot discard work. The fast-front 512-token allowance is a specialized latency response, not a worker precedent.

The margins protect the interactive desktop/control plane, the coin front workload, and model-load transients. Their ownership and combined arithmetic are now known; their numeric rationale and real measured necessity remain unresolved. They are safety margins, not a general reason to leave usable capacity idle or deny benign work. Reconcile observed availability automatically; ghosts, stale observations, conservative defaults, package versions, and unexplained constants must not become terminal gates.

Before changing a capacity ceiling, record its physical or workload rationale and recovery behavior in KT. Review at a glance against this machine profile: a general-worker allowance tiny relative to verified backend capacity is a defect even when tests prove enforcement.