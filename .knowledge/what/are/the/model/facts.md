---
status: green
revised_at: "2026-09-27T12:17:39+10:00"
---

**Qwen3.8-27B-GGUF: the work model.**
- David: this is the minimum competent model for agent work. 4B- and 8B-class models are not used for agent work.
- Weights about 17.5 GB.
- Current JSON-parser test shape: `ctx_size` 131,072 with `--parallel 1` (one lane of 131,072 tokens). Normal two-lane shape is 262,144 total; the per-agent context allowance is preserved.
- Launch arguments: `--batch-size 512 --ubatch-size 128 --poll 0 --prio -1 --spec-type draft-mtp --cache-ram 0` (MTP speculative decoding), plus `--slot-save-path` from the backend for context snapshots. No `--reasoning-budget`. Earlier two-lane memory observation was about 38.5 GB; the 4B about 6.6 GB. The one-lane shape has not been separately memory-benchmarked; its configured 39 GB admission estimate remains conservative.
- Earlier observed speed (not a current benchmark): about 20–25 visible tokens/s for one request with MTP, and about 13 tokens/s aggregate across two concurrent requests. Prefill runs at about 170 tokens/s, so an uncached 20k-token agent prompt costs about 2 minutes of lane time, and generation on the other lane drops to about 1–3 tokens/s meanwhile.
- A hybrid (recurrent plus attention) model: prompt reuse needs a saved state, not merely a shared prefix (`how/does/lemonade/serve/models.md`).
- Supports tool calling.

**Qwen3.5-4B-GGUF: the front desk.**
- Weights about 2.9 GB; kept loaded (pinned).
- Shape: `ctx_size` 65,536 with `--parallel 2` (2 lanes of 32,768 tokens).
- Fast first replies for Coin. Its configured arguments also include `--cache-ram 0`; the server's extra RAM prompt cache is disabled for both models, while CointOS retains its own slot snapshots.

**Lanes are set at load.** `--parallel` is a llama-server start option and the KV buffer is allocated at load, so the lane count is part of how a model is loaded.

**Check what actually loaded.** Lemonade keeps saved recipe options per model. After a load, the effective `launch_command` in Lemonade's health output shows the arguments actually in use. CointOS deliberately loads with `merge_args: false` and `save_options: false`: it supplies the complete configured arguments without changing the saved recipe. Both models are pinned. `backend_llama.models()` checks effective context and requested flags before declaring a model up; health on 2026-09-27 matched both configured shapes.
