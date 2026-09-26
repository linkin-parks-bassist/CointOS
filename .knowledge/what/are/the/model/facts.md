---
status: green
revised_at: "2026-09-26T10:51:40+10:00"
---

**Qwen3.8-27B-GGUF: the work model.**
- David: this is the minimum competent model for agent work. 4B- and 8B-class models are not used for agent work.
- Weights about 17.5 GB.
- Shape: `ctx_size` 262,144 with `--parallel 2` (2 lanes of 131,072 tokens).
- Launch arguments: `--batch-size 512 --ubatch-size 128 --poll 0 --prio -1 --spec-type draft-mtp` (MTP speculative decoding). No `--reasoning-budget`.
- Observed speed: about 20–25 visible tokens/s for one request with MTP, and about 13 tokens/s aggregate across two concurrent requests.
- Supports tool calling.

**Qwen3.5-4B-GGUF: the front desk.**
- Weights about 2.9 GB; kept loaded (pinned).
- Shape: `ctx_size` 65,536 with `--parallel 2` (2 lanes of 32,768 tokens).
- Fast first replies for Coin.

**Lanes are set at load.** `--parallel` is a llama-server start option and the KV buffer is allocated at load, so the lane count is part of how a model is loaded.

**Check what actually loaded.** Lemonade keeps saved recipe options per model. After a load, the effective `launch_command` in Lemonade's health output shows the arguments actually in use. Loading with `merge_args: true` and `save_options: true` keeps the saved recipe equal to the requested one.
