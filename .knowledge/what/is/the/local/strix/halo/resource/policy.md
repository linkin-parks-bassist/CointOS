---
status: "unverified"
created_at: "2026-09-15T22:09:16+10:00"
scope: "project local"
source: "David explicit abundance-first policy; /proc/meminfo and amdgpu sysfs observation; config/resource-policy.json and model-policy.json 2026-09-15"
updated_at: "2026-09-16T17:25:39+10:00"
---

This CointOS host is a Strix Halo machine with nominal 128 GB unified LPDDR5 memory. The operating system currently reports 134149070848 bytes (124.936 GiB) of physical RAM; amdgpu currently exposes a 64 GiB GTT domain. CointOS must use fresh live measurements for admission, including the smaller current accelerator-visible boundary, rather than assuming every physical byte is immediately GPU-addressable.

Policy is abundance-first within those measured boundaries. General agent work receives the largest useful verified context and output allowances; when the backend and client support it, 32000 output tokens is the minimum ordinary-worker allowance. Allocate a fitting backend, reclaim idle lower-priority residency, or queue retained work rather than silently starving an agent. Small limits require a named workload reason and evidence that truncation cannot discard work. The fast-front allowance is a specialized 512-token latency response, raised from the truncating 96-token value; it is not a precedent for worker agents.

Memory reserves protect the interactive desktop, control plane, load transients, and priority recovery. They are safety margins, not a general reason to leave usable capacity idle or deny benign work. Reconcile observed availability automatically. A request may wait for actual physical shortage or higher/equal-priority demand, but ghost claims, stale observations, conservative defaults, package versions, and unexplained constants must not become terminal gates.

Before changing any capacity ceiling, record its physical or workload rationale and its recovery behavior in KT. Review at a glance against this machine profile: a general-worker allowance that is tiny relative to verified backend capacity is a defect even when validation tests prove the number is enforced. Exact harness/backend agreement and SADS recovery are owned by `what/is/intended/live_capacity_contract.md` and `global:what/is/the/agent/continuity/policy.md`.
