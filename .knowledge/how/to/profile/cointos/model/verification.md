---
status: green
revised_at: "2026-10-19T12:16:01+11:00"
---

For selected Gufo, use the ROCm SDK's rocprofv3 launch mode on the same packaged binary, with kernel and HIP-runtime traces in rocpd format. The captured-agent replay in native-profile-20261019/replay-kernels succeeds: 38,001 saved tokens plus a fixed 79-token coding turn, recorded temperature-1 seed-193 sampling, two warmed 32-token steps, and exact output/draft-count agreement across normal/profiled/normal controls. Use rocprofiler_get_timestamp to select generation windows; exclude loading, restore and prefill. Its 24,310 selected dispatches occupy 96.76% of the 3.584-second interval. Native controls vary 17.03→19.29 tokens/s, so no precise profiling-overhead claim follows.

The memory-copy tracer misses four HSA completion callbacks at shutdown, hangs export and produces no database on real snapshot replay. A passing HIP smoke test does not qualify it. replay/run.json verifies tokens but explicitly lacks trace export; replay-kernels/run.json verifies both export and restored production.

Live v7 lacks the startup attachment thread. ROCP_TOOL_ATTACH=1 creates it in a helper, but attachment still fails under YAMA scope 1. Use a controlled profiled child without weakening ptrace policy. Both release and gpu-test presets use RelWithDebInfo and the inspected model kernels use -O2; no hot NDEBUG branch explains the speed gap.

Quantized verification and attention dominate this trace. Source owners are src/models/qwen/hip/kernels/{small_batch_gemm.hpp,small_batch_wave64.hip,prefill_quant_gemm.hip} and attention_decode.hip. Compiler resource reports distinguish private storage from spills: IQ4_XS width-six wave64 has 32 scratch bytes/lane but zero reported SGPR/VGPR spills. Match mapped read-only weights, cold traffic, exact arithmetic and full inference before adopting a dispatch change. Duplicate baseline timings must agree sufficiently to interpret a microbenchmark; draining admission alone does not isolate existing generation.

Extract observed cycle costs from the retained trace: find each DFlash partial-top-k selector, verify its grid-y proposal count against the native step's draft totals, and bracket it by the immediately preceding draft embedding and the next draft embedding. Verify both draft/target embeddings have proposal-count plus one rows. Exclude the final cycle and cross-step gaps. This includes current draft/verification/feedback and next feature injection, not just the target GEMM. replay-kernels/cycle-costs.json has 17 cycles: median milliseconds for 3/4/5/6/7 proposals are 152.7/166.1/182.2/207.9/218.2, with sample counts 1/7/6/1/2. Unequal accepted histories and profiling prevent treating these observations as unprofiled fixed-width calibration. src/models/qwen/dflash_policy.hpp owns deterministic offline costs. Retuning requires matched controls and seeded replay; request-time feedback would break that contract.

For retained llama.cpp/Vulkan experiments, use the packaged GPU timestamp logger alongside the server cycle profiler. Preserve weights, occupied context, sampling, executable and compute libraries. Restore complete paired target/MTP state before each sample; target-only restoration changes draft acceptance.

Packaged b10723 supports these controls without rebuilding:

- `GGML_VK_PERF_LOGGER=1` enables timestamps and waits for each graph's results.
- `GGML_VK_PERF_LOGGER_CONCURRENT=1` times existing dependency groups. Mixed labels cannot attribute all time to one operator.
- Omitting concurrent mode adds node/fusion synchronization: finer attribution, altered execution.
- `GGML_VK_PERF_LOGGER_FREQUENCY=1` prints every graph. Join completed logs by task ID; final events can arrive after HTTP completion.

Bracket profiling with unprofiled controls. Instrumented rates are not production throughput. Refuse active Coin/landing work, group trials into one controlled pause, and restore in finally. Verify recipe, sessions, runtime checks and original autonomy. cancel-restart clears only restarting; go must clear a temporary paused flag when originally active. Model/client liveness is insufficient restoration evidence.

## Device attribution

`/tmp/cointos-mtp-vulkan-profile-probe.py` restores the benchmark owner's private paired fixture: 26,584 prompt tokens, three drafts, loaded capacity six, 131k allocation, inherited sampling. Baseline/concurrent/serial/baseline, two replies each, produce identical 61-token vectors. Baseline median 21.151 tokens/s versus concurrent/serial 19.913/20.013 measures 5.9%/5.4% profiling overhead. The production recipe was restored without long prefill.

`/tmp/cointos-mtp-vulkan-profile-analyze.py` selects generation task IDs and four-column target graphs containing recurrent operators, excluding startup, preparation and draft-only graphs. Forty graphs per mode show:

| Device time per graph | Serial profiling |
| --- | ---: |
| Matrix multiplication | 89.29 ms |
| Attention | 17.07 ms |
| Recurrent computation | 1.77 ms |
| Copies/gathers | 4.42 ms |
| Other | 4.59 ms |
| Total | 117.14 ms |

Concurrent groups total 110.95 ms; matrix-containing groups take 83.88 ms. Matrix multiplication dominates, particularly Q5_K and IQ4_XS feed-forward projections.

## Dispatch and draft depth

`ggml_vk_mul_mat` selects matrix-vector kernels for suitable batches of at most eight columns, matrix-matrix above eight. MTP depth N verifies N+1 columns. `ggml_vk_should_use_mmvq` separately chooses quantized versus floating activations; default enables batched MMVQ except Q6_K on AMD. FORCE/DISABLE comparisons belong to the backend benchmark owner.

`/tmp/cointos-mtp-boundary-probe.py` tests depths 3/7/8/8/7/3 for seeds 123/321, unchanged sampling and paired 26,583-token state. Capacity-six snapshots successfully restore at capacity eight without prefill. All twelve output vectors match their seed's depth-three reference.

| Warmed depth | Seed 123 tokens/s | Seed 321 tokens/s |
| --- | ---: | ---: |
| 3 | 20.65 | 23.78 |
| 7 | 21.02 | 23.43 |
| 8 | 10.21 | 12.48 |

Depth-seven target submission/wait averages 183–184 ms; depth-eight 421–436 ms, with draft cost also increasing from 54 to 64–66 ms. Depth seven's initial cycle costs 1,473 ms, but eight's slowdown persists across repeats. Results establish a regression at the source-defined dispatch boundary, not an isolated attribution of every added millisecond. That MTP trial retained depth three; it does not prescribe Gufo's draft width. The original production recipe and identities were restored.

Evidence lives in the private root located through `/tmp/cointos-woru-capture-evidence.json`: `mtp-vulkan-profile-{evidence,analysis}.json`, per-arm logs, `mtp-boundary-{evidence,analysis}.json` and `mtp-boundary-depths-3-7-8.log`. Source: `ggml/src/ggml-vulkan/ggml-vulkan.cpp` timestamp collection and matrix dispatch; `src/llama-memory-recurrent.cpp` serializes the current recurrent row independently of rollback capacity. Build changes/adoption remain owned by the backend benchmark procedure.
