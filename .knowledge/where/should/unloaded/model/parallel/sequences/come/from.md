---
status: "unverified"
created_at: "2026-09-16T02:58:02+10:00"
scope: "local"
source: "current resource policy, model routing source, focused checks, and installed live unloaded-model qualification 2026-09-16"
updated_at: "2026-09-17T09:57:03+10:00"
---

For an unloaded model, `parallel_sequences` comes from explicit dynamic load policy because Lemonade's downloaded-model registry does not describe a live slot layout. `config/resource-policy.json` currently sets `dynamic_models.parallel_requests` to one. Unloaded metadata verification does not require a registry parallel field; `_model_route` uses a positive observed/model value when one exists, otherwise the positive dynamic-policy value.

For a resident model, routing continues to use the backend-observed slot count and context layout. The value one is a conservative initial work-model layout that preserves the full verified 131072-token backend context for the current single observable Qwen worker. It is not an assertion that the hardware can never serve broader concurrency; future layouts should be qualified per model and context against observed demand and physical capacity.

Installed live qualification carried `parallel_sequences: 1` through an unloaded DeepSeek-Qwen3-8B route, reclaimed idle Qwen3.8 under GTT pressure, loaded and verified DeepSeek, then reclaimed it and restored Qwen3.8 pinned at 131072 while Qwen3.5 remained resident. The former missing-registry-field and route-pressure barriers are closed.