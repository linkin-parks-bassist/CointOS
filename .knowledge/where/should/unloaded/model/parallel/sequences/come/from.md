---
status: "unverified"
created_at: "2026-09-16T02:58:02+10:00"
scope: "local"
source: "observable worker final; config and models diff; 48 tests; fresh real ~/.CointOS snapshot and route output 2026-09-16"
updated_at: "2026-09-16T03:14:20+10:00"
---

`parallel_sequences` for an unloaded model is a requested load-layout decision, not a fact supplied by Lemonade's downloaded-model registry. The registry omits it. Requiring the field in `_verified_model_record` and `_model_route` therefore creates false unavailability before CointOS can call the load producer.

Live resident routes must continue to use the backend-observed slot count and context layout. For an unloaded route, CointOS should use explicit dynamic scheduling intent. `config/resource-policy.json` already owns `dynamic_models.parallel_requests`; `_policy_value` can retrieve it. `_model_route` currently calls `model.get("parallel_sequences", fallback)`, but normalized records contain the key with value `None`, so the fallback is bypassed. Metadata verification also requires the missing registry value.

The current dynamic value 8 is unqualified and conflicts with `config/model-policy.json` workers `initial_concurrency: 1` and the manually qualified one-local-worker practice. With maximum backend context 131072, eight sequences provide only 16384 each, below the ordinary prompt/tool/output/handoff reserve, so using 8 would preserve the barrier in a different form. Initial unloaded work-model residency should start with one sequence; concurrency can later scale from observed demand and a separately qualified per-model layout.

Implementation decision: set `dynamic_models.parallel_requests` to 1; make unloaded metadata verification independent of registry parallel count; in `_model_route`, use a positive observed/model `parallel_sequences` when present, otherwise the positive policy `parallel_requests`, defaulting to 1 only when the policy field is absent. Preserve strict observed layout for resident/shared routes and fresh route validation.

Next check: implement the config value and the two narrow metadata/routing changes, then directly prove a normalized unloaded registry item reaches an admitted one-sequence route. Do not claim live load qualification until `realize` loads and post-verifies an actual unloaded model.

Implementation and qualification 2026-09-16: `dynamic_models.parallel_requests` is now 1; unloaded metadata no longer requires a registry parallel field; `_model_route` uses a positive observed/model value when present and otherwise the positive dynamic policy value. Live resident observation remains unchanged. Three mechanical edits were made by an observable Qwen worker which exited 0; JSON and Python syntax checks pass, all 48 remaining model-admission tests pass, and a fresh real `models.snapshot(~/.CointOS)` showed unloaded routes carrying `parallel_sequences: 1`. At least one downloaded model reached `state: admitted` with no metadata/parallel exclusion. The registry metadata barrier is therefore closed in source.

The live snapshot also showed DeepSeek-Qwen3-8B now deferred only by `gtt_capacity` while both resident slots are occupied. This proves route-level pressure/reclamation ordering is the next barrier: routing must account for reclaimable idle work residency before denying the candidate.
