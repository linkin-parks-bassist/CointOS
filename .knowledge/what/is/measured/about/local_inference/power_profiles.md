---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local host measurement
source: controlled measurements recorded 2026-09-04 in Git history for power-profile-benchmarks.md
verification: Preserved only the controlled protocol and comparison; excluded incomparable live observations.
review_when: Re-measure after firmware, backend, model, or hardware changes.
---

With Qwen3.6-35B-A3B-MTP Q4_K_XL, a fixed 36-token prompt, 512-token deterministic
output, and prompt cache disabled, three purple-mode runs averaged 82.32 generated
tokens/s and three orange-mode runs averaged 83.76 tokens/s. Orange was about 1.7%
faster and substantially louder. Linux reported `performance` for both LED modes,
so the distinction appears below that interface. Do not compare these controlled
figures with long-context live-agent observations.
