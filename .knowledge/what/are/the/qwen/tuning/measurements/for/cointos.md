---
status: green
revised_at: "2026-10-24T10:42:39+11:00"
---

Matched greedy continuation of the retained real 95,766-token prefix favors the existing adaptive policy over fixed one/two/three proposals. draft-greedy-20261019/{run,summary}.json uses temperature zero, seed 193, three 32-token chunks per measured mode and a restore before each trial. All six runs emit the identical 96-token vector. Adaptive before/after reaches 21.35/22.73 native tokens/s (80/82 drafts accepted); fixed one 12.76, two 15.78/16.00 and three 17.95. Full-width round medians are 150.2 ms for one, 177.6/175.7 for two and 209.9 for three. Two's repeat and adaptive controls show timing drift; these results reject forcing a short default on this high-acceptance greedy history. They do not establish the best policy for low-acceptance sampled work. Model/client identity, authority and active autonomy restore.

The private long-context cost fit in draft-cost-candidate-20261019 is not selected for production. CPU checks change 201 C1 choices while preserving protected cases/saturated widths. trial-longer/{run,summary}.json restores 95,877 tokens, retains effective sampling per trial/chunk and measures 192 sampled tokens per mode/seed:

| Seed | Baseline tokens/s | Candidate tokens/s |
| --- | ---: | ---: |
| 193 | 13.83 | 13.04 |
| 321 | 13.04 | 14.40 |
| 777 | 13.26 | 13.27 |

Aggregate throughput is 13.37 versus 13.54 (+1.28%). Mixed seeds, different sampled trajectories and reversal of seed 193's shorter result establish no dependable gain. Greedy baseline/candidate emit identical 96-token vectors at 12.90/13.68; the candidate's 192-token sampled replay exactly preserves tokens/draft counts at 12.92 versus 13.04. Keep the original policy; further testing needs a revised cost hypothesis. Production, clients, authority and active autonomy restore after 227 seconds. hardware-observation.json records a baseline segment at 98–100% GPU utilization, 60–62°C and 1.87–1.99 GHz; it establishes no thermal bottleneck. Short trials establish no adoption case.

Gufo retains adaptive maximum seven. Installed configuration: 32 tokens/10 seconds; source: 32/30. Verify effective values through the daemon. Calibration's 32-token chunks establish no default.

draft-calibration-20261019/{recipe,run,summary}.json records an unprofiled, warmed native replay at 95,845 occupied tokens: 95,766 captured agent tokens plus a fixed 79-token coding turn. Sampling is temperature 1, seed 193, top-k 20, top-p .95, min-p .05. Each measured output has 32 tokens. A private executable overrides only draft selection between trials while retaining the original policy/maximum in the snapshot format. Its mode zero exactly matches production tokens and draft counts. Per-round telemetry includes proposal, verification and feedback; the final pending-token advance remains in the complete generation timer.

| Fixed proposals | Native output tokens/s | Accepted/proposed | Median full-width round ms |
| --- | ---: | ---: | ---: |
| 1 | 13.29 | 15/16 | 142.5 |
| 3 | 13.27 | 19/34 | 194.8 |
| 4 | 10.74; replay 10.99 | 18/47 both | 240.7; replay 223.5 |
| 5 | 14.29 | 21/40 | 237.1 |
| 7 | 24.19 | 27/27 | 310.4 |

Production adaptive controls run 23.06 before and 24.93 after; private adaptive reaches 24.05 with identical vectors/counts. Fixed-four snapshot replay exactly reproduces its tokens and counts. Client PIDs, sessions, recorded spend and authority survive the 168-second model/client parking interval. captured-prefix.bin is a checksum-verified 6.52 GB reusable physical fixture. Explicitly restore the original paused state: go resumes autonomy; cancel-restart clears only restarting. The private harness now checks both.

Different widths consume different RNG paths and produce different sampled histories. These short samples cannot establish a policy gain; adaptive/seven's perfect acceptance cannot predict low-acceptance work. Four's moving median straddles five's observation, so a four-versus-five cost cliff is unproved. Long-context cost estimates still need qualification on ordinary sampled work; a deterministic cost candidate must preserve saturated throughput and seeded restore replay. Keep production sampling quality and seeded restore replay. No private calibration operation is installed.

Historical llama.cpp tuning remains relevant only within its measured recipes:

- mtp and mtp-remaining: 8,081 prompt/256 output; draft depths 1/3/6/off generation **17.051/19.567/14.420/11.342**. Vectors vary; quality is unproved.
- ubatch: 128/256/512 microbatch prefill/generation **178.949/21.070**, **180.682/20.241**, **175.554/20.275**.
- backend-sampling: greedy versus production temperature 1/top-k 20/top-p .95/min-p .05; CPU/backend generation **17.186/17.736** versus **16.218/15.630**. CPU target sampling remains the historical comparison default.
- batch: 256/512/1024 logical batch prefill/generation **176.218/20.764**, **168.304/20.713**, **170.013/20.897**. Randomized repetitions and useful-work validation remain necessary.
- kv-code: 31,360 prompt; f16/Q8 generation **14.374/13.844**, continuations **11.694/11.642**. Q8 snapshots shrink 2.213→1.250 GB and restore about 327→166 ms, but prefill worsens. Isolate snapshots across native K/V type changes.
- long-ab: matched 77,028 prompt, four samples/build; stock/patched generation **13.055/13.089**, overlapping ranges. No meaningful regression or historical sustained-25 reproduction.

The experimental llama per-request MTP depth controls are disabled in production. The experimental mtp-request-depth patch requires LLAMA_MTP_REQUEST_DEPTH and validates depth within loaded capacity. CPU checks verify executed depths, repeated/restored vectors and invalid-depth rejection. GPU depth evidence restores identical 26,583-token paired state: depths 3/4/6 produce identical seed outputs but no robust speed gain; first-use depth-4/6 penalties remain unexplained. MMVQ evidence shows small forced-kernel gains, sometimes changed vectors; disabling kernels slows generation. Do not adopt from these fixtures.

Rebuild changed objects/server archive/common library using /tmp/cointos-mtp-depth-component-build.json; available shader compiler cannot build current cooperative-matrix shaders. Update all regular-file libllama-common.so aliases, including loader-selected .so.0, and verify mapped hashes. Dependencies: /tmp/cointos-llama-deps/root; run test-chat from source root.
