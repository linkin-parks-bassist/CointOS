---
status: green
revised_at: "2026-09-26T02:34:33+10:00"
---

In emergency mode, the prepared Sole Survivor job has `authority_profile=sole_survivor`, `role=sole_survivor`, and a 32768-token minimum context plus reasoning/tool-calling requirements. The pinned Qwen3.5-4B emergency model has a verified 32768-token per-sequence allocation but lacks the ordinary `reasoning` capability tag; ordinary default prompt/tool/output/handoff reserves also exceed that allocation. An ordinary reroute therefore selected a different model, so an executor that first synthesized `use_loaded` and then rerouted under the realization lock deferred with `route changed before model realization`.

Installed `ecosystem.models.safe_routes` applies the emergency policy only for that exact Sole Survivor authority and role while resource mode is `emergency`: it routes against the configured emergency chat model with configured emergency context reserves, still using fresh observed model metadata and normal physical capacity validation, and rejects any other model. `ecosystem.executor.run_once` uses the same `route` path before and after realization instead of a synthetic decision. `config/resource-policy.json` supplies emergency reserves of 4096 prompt, 4096 tool, 8192 output, and 8192 handoff tokens. The route must still be loaded, admitted, and have at least the configured 32768 per-sequence context. This exception does not alter ordinary job routing or make a requested model hint binding.

The direct route/validate smoke against the live emergency inventory admitted Qwen3.5-4B at 32768 context and parallel 2. Focused source tests for resource control, executor, inference capacity and model admission passed. After installation the Sole Survivor reached `running` with a verified worker lease and inference sequence; the separate emergency drain-admission exception is required for that result.
