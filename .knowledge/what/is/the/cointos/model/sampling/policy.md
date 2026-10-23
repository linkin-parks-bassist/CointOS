---
status: green
revised_at: "2026-10-14T23:34:40+11:00"
---

Sampling defaults are inherited, not user-selected. Captured OpenCode requests omit sampling fields; production `/props` reports temperature 1/top-k 20/top-p .95/min-p .05. GGUF `general.sampling` metadata supplies the first three; min-p is the native default. Live launch/environment contain no overrides. `common_init_sampler_from_model` imports metadata unless explicitly overridden. Disclose effective sampling: temperature changes output distribution and speculative acceptance, requiring quality validation. Woru's fast burst used these same settings; see the benchmark owner.
