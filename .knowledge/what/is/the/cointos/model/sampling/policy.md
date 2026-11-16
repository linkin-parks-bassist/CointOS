---
status: green
revised_at: "2026-11-06T09:28:41+11:00"
---

Ordinary model defaults are inherited, not user-selected tuning: temperature 1, top-k 20, top-p .95, min-p .05. Captured OpenCode requests omit sampling fields. The Gufo model recipe explicitly carries these defaults; on the llama path, production /props reported them, with GGUF general.sampling metadata supplying the first three and native min-p supplying .05. common_init_sampler_from_model imports metadata unless overridden. Woru's fast burst used the same defaults; its benchmark owner retains that evidence.

Coin is an explicit exception: coin.complete requests temperature .4. gateway.SAMPLING forwards per-request fields; backend_gufo.think overlays them on model-recipe defaults and backend_llama.think forwards them into /completion. Thus Coin experiments must use .4 when matching that path, while ordinary OpenCode-agent experiments use their effective defaults. The original math steer experiments used temperature 1; the agentic-v2 Coin replays and saved-state comparisons use .4. This sampling difference accompanies the task/effort/cap differences; it is not by itself a demonstrated cause of the failed trial.

Disclose effective sampling in comparisons: temperature changes output distribution and speculative acceptance, so a change requires quality validation. Stored defaults grant no authority to tune production.
