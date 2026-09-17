---
status: "unverified"
created_at: "2026-09-16T17:07:26+10:00"
scope: "local"
source: "source duplicate realization gate removal; 100 GiB capacity repair and installed checks 2026-09-17"
checked_at: "2026-09-17T12:52:00+10:00"
updated_at: "2026-09-17T12:53:53+10:00"
---

`models.realize` previously validated that its selected unloaded route matched a fresh inventory and coherent backend allocation, then called the older `admission(model_id, inventory)` before `load_model_with_idle_reclamation`. That legacy function separately read GB-form `desktop_and_control_reserve_gb`, `model_load_transient_reserve_gb`, `unknown_model_reserve_gb`, and `gpu_boundary.gtt_limit_gb`, duplicating the byte-form capacity policy used by safe routing and inference allocation. Its unknown-model fallback alone reserved 64 GiB and could make the legacy arithmetic require 108 GiB (`32 + 12 + 64`) before considering the actual model or idle reclamation.

The redundant realization call was removed first. The subsequent reserve audit found no remaining production caller of `models.admission()`, so the function, its `admission` configuration section, the duplicate `gpu_boundary` section, and its obsolete direct refusal test are now removed. Unloaded realization proceeds from coherent routed allocation to fresh residency observation and the verified reclamation/load producer. The canonical byte-form policy remains under `physical_capacity` and `inference_capacity`.

The configured 100 GiB GTT limit is the machine's real hardware GPU allocation capability. A 64 GiB value from one amdgpu GTT sysfs domain was previously misread as a physical cap; `models.snapshot()` and `inference_capacity.resource_envelope()` no longer take the minimum of that observation and configured capability. Fresh GTT use remains an occupancy signal. Owner: `why/is/the/amdgpu/64/gib/gtt/total/not/the/gpu/allocation/capacity.md`.

Focused checks pass: JSON validation, source compilation, 139 existing inference-capacity/model-admission/resource-control checks, and three resident-pool checks. Installed live snapshot reports the 64 GiB informational sysfs domain, 33.553 GiB current use, 100 GiB admission capacity, a verified envelope, and no legacy admission sections.
