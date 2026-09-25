---
status: green
revised_at: "2026-09-26T01:47:59+10:00"
---

An unloaded model has no live slot layout in Lemonade's downloaded registry, so its first load uses explicit conservative dynamic policy. Installed `config/resource-policy.json` sets generic `dynamic_models.parallel_requests` to one and has no named Qwen slot override. `_model_route` retains support for an optional positive `parallel_requests_by_model[model_id]` when one is explicitly configured, but otherwise uses the generic value. Unloaded metadata verification does not require a registry parallel field.

For a resident model, routing uses freshly observed backend slot count and context layout. Installed `backend_profile_policy` and `backend_profile_scheduler` can select a demand-sized physical profile up to an explicitly evidenced ceiling fingerprinted to exact weights, recipe and per-sequence context. The loaded Qwen3.8 backend has two observed 131072-token MTP sequences, an evidence-backed runtime ceiling of two, and passed an idle manual 2→1→2 reload; this is not a permanent Qwen constant. Automatic demand-driven growth remains disabled pending parked-worker and pressure qualification. A conservative initial slot is not a claim that hardware can never serve more.

Prior DeepSeek qualification carried `parallel_sequences: 1` through an unloaded route, reclaimed idle Qwen3.8 under GTT pressure, loaded and verified DeepSeek, then reclaimed it and restored Qwen3.8 at 131072 while control remained resident.
