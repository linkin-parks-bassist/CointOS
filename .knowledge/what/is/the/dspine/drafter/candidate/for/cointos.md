---
status: green
revised_at: "2026-11-16T19:04:08+11:00"
---

DSpine is Tencent Hunyuan's five-layer ~2B speculative drafter for Qwen3.8-27B (arXiv2609.36173): five target-layer hidden states feed a 16-token block. Ajay9o9/llama.cpp's `dspine` branch supports it; the deployed static Vulkan build is d493f84. The server-build owner identifies binary hashes and HIP build instructions.

**Objective:** raise the generation-speed floor above David's reported steady low-20s tok/s before DSpine. Peak decode and whole-factory throughput are separate; this floor remains unestablished.

**Trial status:** experiments are paused. The retained 27B comparison used Vulkan d493f84, built-in MTP depth3, three131k q8 resident slots, one lane and the original steer. Those are trial conditions; current shared Qwen selection belongs to model facts. DSpine remains available. KV comparison is incomplete; resume only on request.

**Captured-prefix comparison:** private evidence `~/.local/state/cointos/dspine-floor-20261109-{b,c,d,e-hip,f-hip-short}/`. Four prefixes of one real Operator trace, three seeds each, 64 output tokens/sample; temperature1/top-k20/top-p.95/min-p.05, matched target weights/vector and one private slot. All completed samples return64 tokens. Warmup excluded; table values are median native decode tok/s, not guaranteed floors. MTP3p means probabilistic width3.

| Prefix | Vulkan MTP3p | Vulkan DSp15 | HIP MTP3p | HIP DSp3 | HIP DSp15 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 9195 | 24.5 | 17.8 | 26.5 | 28.4 | 31.6 |
| 9515 | 15.7 | 6.8 | 16.4 | 17.3 | 11.6 |
| 9835 | 28.8 | 43.5 | 30.8 | 31.9 | 72.7 |
| 10155 | 28.9 | 50.4 | 30.8 | 31.9 | 88.7 |

Pooled decode: Vulkan greedy MTP20.7, MTP3p22.9, DSp15-Q4 16.4, DSp15-Q8 17.8; HIP MTP3p24.1, DSp15 29.1, DSp3 25.1. Repeated Vulkan greedy controls match counts/timings. Sampled paths differ across modes/backends; cold versus incremental preparation also changes trajectories. Compare identically prepared arms. These short tests establish neither long-context/resident-shape speed nor output quality.

Q8 does not remove the trough (Vulkan hard-prefix median7.2). Short widths sacrifice peaks: HIP DSp2 hard/easy medians16.2/25.7; DSp4 15.0/35.0. Vulkan DSp2/3/4 give hard-prefix medians15.7/14.8/11.8. Vulkan probabilistic MTP widths1/2/3/7 give16.3/17.2/17.2/5.9 on the cold hard prefix. No static setting tested establishes steady low20s.

`patches/dspine/benchmark_floor.py` preserves production through the existing parking/recovery harness. `--recover OUTPUT` handles interruption; `--summarize OUTPUT` uses matched phase denominators without touching production. Trials are assisted boundaries, never autonomous acceptance. Preserve sessions, credentials, spend and slots; verify resumed generation. The baseline fork's CPU rejection-sampler test passes, not Qwen tool/quality qualification.

**Remaining hypotheses:** baseline MTP proposal sampling copies temperature/seed but fixes top-k10, whereas target requests use top-k20/top-p/min-p. Isolated `patches/dspine/proposal-shaping.patch` forwards those filters; paired HIP tests give only ~3% pooled gain with mixed seeds, not a proven floor improvement. It is unselected. Confidence cutoffs.1/.2 also fail to remove the trough. DFlash's acceptance callback is a no-op; shared draft-context initialization does not establish an adaptive MTP fallback by listing both types.

Two live lanes worsened generation to ~1 tok/s/~14% acceptance during peer prefill.40–100k contexts prefill at ~200–270 tok/s and can dominate wall time. Prior q8 headroom was ~20–27GB; remeasure after retiring an idle probe holding ~11GiB; f16 left ~3–13GB and was reverted. Each resident slot costs roughly10GB. what/is/the/plan.md owns remaining qualification.
