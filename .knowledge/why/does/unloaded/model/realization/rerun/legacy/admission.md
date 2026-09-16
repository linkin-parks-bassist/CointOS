---
status: "unverified"
created_at: "2026-09-16T17:07:26+10:00"
scope: "local"
source: "source duplicate realization gate removal and checks 2026-09-16"
checked_at: "2026-09-16T17:14:33+10:00"
updated_at: "2026-09-16T17:16:47+10:00"
---

`models.realize` previously validated that its selected unloaded route matched a fresh inventory and coherent backend allocation, then called the older `admission(model_id, inventory)` before `load_model_with_idle_reclamation`. That legacy function separately reads `admission.desktop_and_control_reserve_gb`, `model_load_transient_reserve_gb`, `unknown_model_reserve_gb`, and `gpu_boundary.gtt_limit_gb`. The same policy file also carries byte-form reserves for `safe_routes` and inference capacity. The configured legacy GTT limit is 100 GiB while the live amdgpu GTT domain is 64 GiB; safe routing uses fresh/live-bounded facts and carries unloaded pressure into the verified reclamation producer. The duplicate legacy check could therefore disagree with the route and reject before reclaiming an idle work residency.

The redundant call is removed from `realize`; the compatibility `admission()` function remains for direct callers. Unloaded realization now proceeds from coherent routed allocation directly to fresh live residency-limit observation and the verified idle-reclamation/load producer. Route validation, control/operator protection, unload/load postconditions, and wait outcomes are unchanged. `py_compile`, all 47 model-admission tests, seven shared-model routing tests, and a direct injected check proving a legacy-admission exception is not consulted all pass. Installed unloaded-model exercise can reuse the prior qualified DeepSeek path when next needed.