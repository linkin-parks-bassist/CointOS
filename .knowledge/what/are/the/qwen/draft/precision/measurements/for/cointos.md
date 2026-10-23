---
status: green
revised_at: "2026-10-19T20:20:19+11:00"
---

Q8_0 passes GPU loading, RAM checkpoint restoration, seeded replay and a small tool-call contract. No higher-precision draft benefit is established; production remains Q4_K_M.

The [publisher's Q8_0 artifact](https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2-GGUF/blob/2d9571f8ce46e151f61c6499c99dee6079e1d610/Qwen3.8-27B-DFlash2-Q8_0.gguf) is 2,056,414,816 bytes, SHA256 c18e800daedc59ca68fd13b6a856d795746af6d399a9279ac6a277d1d422f87e. Its downloaded checksum matches. CPU inspection matches Q4 architecture, non-general metadata and all 81 tensor shapes: 32 F32 vectors and 49 Q8 matrices replace 45 Q4_K and four Q6_K matrices.

Private evidence lives under ~/.local/state/cointos/workflow-observation-20261019/. draft-precision-smoke/{recovery.json,harness.py} and draft-precision-smoke-summary.json qualify an 8,504-token fixture requiring exactly record(value=37), without commentary. Both precisions pass greedy and sampled seeds 193/321/777; seed-193 replay preserves tokens and draft counts, and Q4/Q8 greedy vectors match. All 12 cases emit 25 tokens with identical 20/28 draft acceptance and five rounds. Q4 greedy runs at 31.87 tokens/s before and 33.13 after; Q8 reaches 33.15. Sample-193 Q4/Q8/control rates are 30.98/31.45/33.10. These short replies and control drift establish no useful speed gain. Single cold prefills take 21.44/19.99 seconds; they are not repeated throughput evidence.

The 112.64-second trial restores original model identity, configuration, Coin and all three agent processes, sessions, spend and autonomy. Quarter-second memory sampling records a 37.02 GB minimum against the unchanged 24 GB reserve. Owned temporary snapshots are removed and the private scope is inactive. draft-precision-smoke-live-summary.json verifies resumed worker generation and preserved identities. CPU recovery controls cover private-socket disconnect and foreign-scope refusal. Model identity, not native PID, survives a draft replacement.

The earlier 95,877-token coding-continuation comparison is invalidated by mismatched checkpoint storage: Q4 used tmpfs, Q8 ext4. Q8 prefill completed, but save timed out after 300 seconds amid heavy I/O, before generation. storage-mismatch.json preserves the rejected harness and recovery evidence. Its Q4-only rates of 12.936 greedy and 14.183/13.148/13.337 sampled tokens/s remain observations, not an A/B result. This failure does not establish Q8 incompatibility or slowness.

Current harness storage is matched tmpfs with socket/checksum preflight and peak-save headroom admission. The small successful trial does not qualify simultaneous long-context checkpoint peaks. Cross-precision sampled vectors may differ because proposal paths consume different RNG draws.

Blocker: No completed matched long-context Q4/Q8 generation comparison exists.

Next check: Budget original-state, both long ready files and transient host staging before a matched coding trial; require exact replay, unchanged-Q4 timing controls and useful-work evidence before selection.
