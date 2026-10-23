---
status: green
revised_at: "2026-10-18T22:33:29+11:00"
---

These are historical llama.cpp experiments; current Gufo DFlash2 measurements belong to what/are/the/qwen/backend/measurements/for/cointos.md. Matching draft names do not make engine results interchangeable.

Target-only snapshots lose useful Qwen MTP state. mtp-state evidence fixes 26,584 prompt/seed123/61 output: fresh/paired/target-only generation **20.109/20.114/12.541**, draft acceptance **70/70/28.3%**; all output vectors match. Paired repeat/recovery restores **20.301/20.333**. Paired state adds 109,522,008 draft bytes, 20,480 boundary bytes and a 32-byte trailer to 1,899,782,596 target bytes. The mtp-state patch follows the stop patch; boundary embedding corrections and malformed/legacy/stop/tool fixtures are verified. One mismatch also occurs baseline, so universal fidelity remains unproved. Legacy snapshots lack draft history.

Passive Qwen costs evidence covers 647 seconds: a reader advances 20,368→54,160 without lost progress, using 278 prefill seconds while peers total 261 decode seconds. At 43–45k, native chunks span **12.20–23.55**; fully accepted drafts approach four tokens/cycle at 169–174 ms. At 92k cycles reach 202–207 ms. Acceptance length and cycle cost both matter; the historical sustained 25 remains unexplained. Host cycle profiling charges asynchronous work to later waits; [GPU verification profiling](../../../../../../../how/to/profile/cointos/model/verification.md) owns device attribution.

DFlash evidence: 8k MTP/width4/width7 generation **15.806/17.626/13.786**. At 31,360 code prompt, MTP/width4 **14.831/14.702**, continuations **12.303/12.052**; no gain. Fresh/restored 8,195-code continuity gives Q4 **16.641/16.817**, Q8 **17.718/16.530**; no consistent target-only penalty or Q8 gain. Registered trials remain available; do not adopt from short prose gains.

Splash requires Apple/Darwin/arm64/Xcode/Metal4; direct AMD execution is unavailable. Its Apache-2.0 scheduler/cache ideas do not prove speed; AMD needs concrete MetalBackend operations/kernels ported. Source: /tmp/cointos-splash-source at 8a2b42069923d483151372b615f6182c72c2b6cd. The authorized AMD assessment and vLLM conversion constraints remain open. Qwen DFlash draft provenance belongs with model/service evidence; these experiments do not change MiniCPM's current one-lane recipe.
