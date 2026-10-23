---
status: green
revised_at: "2026-10-19T19:28:39+11:00"
---

Production uses Gufo Qwen3.8-27B UD-Q4_K_XL with DFlash2 Q4_K_M, adaptive maximum seven. Live chunks/slices are 96 tokens/60 seconds; source defaults remain 32/30. Short greedy peaks do not establish ordinary sampled or sustained factory throughput. Draft-precision comparisons have their own owner: what/are/the/qwen/draft/precision/measurements/for/cointos.md.

A captured-agent v7 trace at 38,080 occupied tokens is 96.76% GPU-kernel busy during generation: 61.6% of summed kernel time in quantized verification and 23.5% in attention. Normal/profiled/normal vectors and draft counts match; unprofiled controls range 17.03–19.29 native tokens/s. This establishes neither speedup nor precise profiler overhead (native-profile-20261019/replay-kernels/{run,profile-summary}.json).

IQ4_XS occupancy hints and distributed reduction match screened outputs but show no consistent cold mapped FFN gain; production remains unchanged (quant-{wave-hint,distributed}-20261019/decision.json). Existing one-tile width-five down geometry predicts only ~0.36% total-time benefit in that trace; full inference is unqualified. Private storage is not reported register spilling.

Six-row coefficient-before-token scheduling is rejected, including the original-loop variant. Original/unrolled/rolled use 115/101/99 VGPRs with unchanged private/LDS storage and zero spills. Cold mapped FFN medians (ms):

| Shape M×K | Original | Unrolled | Rolled |
| --- | ---: | ---: | ---: |
| 5120×17408 | 0.509 | 0.654 | 0.629 |
| 17408×5120 | 0.485 | 0.595 | 0.585 |

Both variants match original bits in 2,438,424 comparisons; 648 selected-row FP64 checks pass 1e-6 term-normalized tolerance, worst 2.60e-8. All twelve rounds remain; eleven pairs after the slow first baseline favor original on both shapes. Static counts do not measure executed work. No full-model candidate exists (quant-coefficient-{schedule,rolled}-20261019).

Four independent QK scores before ordered softmax/value updates are not promoted. Forty partial/output comparisons are exact; the limited first-head/three-component FP64 screen and cold rotating KV/O2 recipe remain in attention-scores-20261019/decision.json. Warmed 32,771-token four-row gains are noisy, five rows flat and shallow four rows slightly regress. VGPRs 74→73 leave occupancy/LDS and zero scratch/spills unchanged. Failed harness trials are excluded; restored identities and resumed generation are verified.

An unmatched natural reviewer at 57,368 prompt tokens produced 352 tokens in 21.404 native/23.822 wall seconds (16.45/14.78 tokens/s), accepting 265/373 drafts over 73 rounds. AC/performance, zero PSI/native swap, 54–55 W PPT and 60–61°C are observations, not controlled comparisons (reviewer-observation-20261019/summary.json).

Historical 103.7k–104.8k sampled work varied 10.11–15.18 native tokens/s and 47.4–82.4% acceptance across adjacent 32-token phases. Target-only phases gave 7.55–7.68; one 64-token phase gave 15.50 at 79.6%, followed by 32 at 15.18/82.4%. These are not exact-text chunk controls or current settings (live-speculation-20261019/controls.json).

The v7 continuation fix preserves learned draft policy and consumes its published pending token once. On a captured 41,150-token prefix plus a fixed coding turn, v5/v7 greedy vectors match at 20.496/20.535 native tokens/s; sampled seed-193 paths differ at 20.346/19.752. No speedup is established. Restore/tools/reasoning/client/session/budget/authority checks pass. Earlier v6's apparent 16–18% gain is invalid: reasoning closure failed and it rolled back (draft-policy-continuation-20261019-v3/activation.json).

Captured instructions and 52 tool definitions render to 20,395 tokens before assignment/history: tool-only 12,836, instruction-only 7,613 including framing. Pinned KT descriptions lack suspected repeated MCP boilerplate (live-speculation-20261019/static-prefix.json). Equal-prefix repair removes false restores, not intrinsic decode scaling.

Matched local qualification holds actual weights, recorded vectors, 131,072 allocation and request sampling. The prefix-fix recheck reuses its recorded llama/AR reference, not a new simultaneous baseline:

| Backend/mode | Repetitive fixture median native decode tokens/s |
| --- | ---: |
| Prior llama.cpp, configured draft-mtp | 31.6655 |
| Gufo DFlash2 initial qualification | 48.0619 |
| Gufo after prefix-restore fix | 44.3215 |

The fixture has 2,236 input tokens, 32 warmup and three 256-token measurements in 96/96/64 steps. Each accepts all 218 proposals over 35 rounds: exceptionally favorable speculation. Short code samples accept 44/61 and 35/38 at 29.08/33.40 tokens/s. Greedy uses seed 193, top-k 20, top-p .95, min-p .05. Recheck spans 41.95–46.30; median 256 tokens take 5.77598 native/5.77944 adapter seconds. Including 5.89241 seconds prefill yields 21.93 output tokens/s. No accepted-draft double counting occurs; greedy equals the native AR reference, not a cross-engine distribution proof (gufo-dflash-{qualification,prefix-qualification}-20261018).

A 7,707-token dedupe_runs source fixture passes five executable cases, including nonhashable values, None and input preservation. Greedy/sampled total prefill-plus-generation walls: llama 43.325/38.684 seconds, first DFlash 19.310/18.624, prefix recheck 21.619/21.658. This is narrow coding latency, not general quality.

llama timing uses predicted_n/predicted_ms; Gufo includes bounded native generation and pending-token consumption. Adapter timing includes transport/prefix preparation; explicit prefill stays separate. Repeated prefills can reuse different prefixes and are not matched cold controls. Compare actual sampling, occupied context, restore costs and concurrent load.

Earlier AR-only Gufo measured 11.555 versus llama 31.407 on the repetitive fixture. An uncontrolled v4 live sample generated 778/139.283 native seconds (~5.59 tokens/s) at 69k–72k with concurrent Coin, steps ~3.8–14. There is no matched llama control; historical 32-token steps followed overdue-preemption diagnostics, while current settings are owned above.

Historical build evidence uses 16,384 allocation, 1,151 input, 128 output and three greedy runs: Vulkan b10723 prefill/decode 191.78/21.76 versus ROCm b10707 247.96/16.25. Revisions/vectors differ; prefill gains do not justify slower decode (/tmp/cointos-backend-speed-evidence.json). At 131,072, packaged/local-patched/packaged-libraries-plus-patched-server medians are 184.408/21.401, 184.970/17.983 and 191.763/21.668. Reject the local compute regression; its component is unknown (/tmp/cointos-lemonade-{patch,packaged-patch}-evidence.json).

The stop patch targets b10723 010be9683afabe14ce299197b38c329f94bae568. Twelve vector pairs match and five overruns are corrected. Word/EOS retention and shared warm/cold mismatch prevent universal fidelity claims. Native evidence verifies continuation at 33k and restores 62,789/63,070 and 95,738/95,755. Suspended states alone do not prove rereading. The compaction benchmark owner retains the disabled summary candidate.
