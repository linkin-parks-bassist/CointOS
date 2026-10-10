---
status: green
revised_at: "2026-10-10T16:58:17+11:00"
---

**Qwen3.8-27B-GGUF: the only model.** It runs agents and Coin.
- User policy: this is the minimum competent model for agent work. 4B- and 8B-class models are not used, including for Coin: the user judged the Qwen3.5-4B quick reply worthless and it was removed from config on 2026-10-10. Until a paused full installation runs and Lemonade unloads it, the old running daemon may still hold the 4B (about 7 GB).
- Weights about 17.5 GB.
- Current work shape: `ctx_size` 131,072 with `--parallel 1` (one lane of 131,072 tokens). Normal two-lane shape is 262,144 total; the per-agent context allowance is preserved.
- Launch arguments: `--batch-size 512 --ubatch-size 128 --poll 0 --prio -1 --spec-type draft-mtp --cache-ram 0` (MTP speculative decoding), plus `--slot-save-path` from the backend for context snapshots. No `--reasoning-budget`. Two-lane calibration was about 38.5 GB. The one-lane shape has not been separately memory-benchmarked; its configured 39 GB admission estimate remains conservative.
- Calibration evidence, not a current benchmark: about 20–25 visible tokens/s for one request with MTP, and about 13 tokens/s aggregate across two concurrent requests. Prefill runs at about 170 tokens/s, so an uncached 20k-token agent prompt costs about 2 minutes of lane time, and generation on the other lane drops to about 1–3 tokens/s meanwhile.
- A hybrid (recurrent plus attention) model: prompt reuse needs a saved state, not merely a shared prefix (`how/does/lemonade/serve/models.md`). With its chat template, `enable_thinking: false` changes the rendering from about the third token, so a request toggling it shares no reusable state with the same conversation rendered with thinking on.
- Supports tool calling.

**Size provenance.** The configured admission size (`memory_gb` 39) rounds up a live loaded-memory observation of about 38.5 GB recorded during the 2026-09-26 scheduler rebuild. The configured weight estimate (17.5) originated in this model-facts leaf when the fresh CointOS base was created, then was copied into config by the later dashboard commit. No underlying file-size measurement or external source was retained, and the Lemonade-owned GGUF paths are not stat-readable by the current account. Treat it as an inherited estimate until measured through Lemonade or another authorized interface.

**Lanes are set at load.** `--parallel` is a llama-server start option and the KV buffer is allocated at load, so the lane count is part of how a model is loaded.

**Check what actually loaded.** Lemonade keeps saved recipe options per model. After a load, the effective `launch_command` in Lemonade's health output shows the arguments actually in use. CointOS deliberately loads with `merge_args: false` and `save_options: false`: it supplies the complete configured arguments without changing the saved recipe. The model is pinned. `backend_llama.models()` checks effective context and requested flags before declaring a model up.
