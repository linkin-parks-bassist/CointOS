---
status: green
revised_at: "2026-10-24T10:42:39+11:00"
---

Coin and construction use Gufo Qwen3.8-27B UD-Q4_K_XL: one 131,072-token lane with DFlash2 Q4_K_M, adaptive policy and maximum draft width seven. An OS memory-stop during two-engine diagnostics prompted the user's shared-Qwen choice. MiniCPM remains unloaded. NPU work is deferred.

Upstream is pinned to 1f97092333af10f29887b098d9cb8a041610004a. The installed package is ~/.local/share/cointos/gufo/1f970923-native-dflash-v9-header-20261019. V9 preserves snapshot bytes and continuation; how/does/gufo/serialize/cointos/context/snapshots.md owns same-byte/replay and save-timing evidence. build.json binds binary, libraries, native sources and build-time Python adapters; later live adapter qualification is separate; the launcher requires its named TheRock SDK without temporary library paths. Target SHA256 is 3f227079003add2511437e5b1e94812e363385225bf6a9b47b0054a72bc8b01e; draft SHA256 is 1a25c56858e1ebe93f2718ac1d49d1151f9323325c1bbfd6209370f4db131ebd.

patches/gufo wraps TextModelRunner in a private Unix-socket process. native-control.patch detaches the HTTP scheduler and reuses native chat/tool parsing. backend_gufo owns transport/lifecycle, backend_native dispatches per model and backend_chat shares conversation preparation/output parsing. Token vectors avoid retokenization. Config names executable, model_path, socket, sha256 and optional dflash/sampling objects. Requests override sampling defaults: temperature 1, top_k 20, top_p .95, min_p .05, repetition window 64. Sampler orders prevent cross-engine distribution claims.

Installed control separates CPU-only render/tokenize/text from mutable model ownership. One metadata mutex overlaps inference; prefill/think/save/restore retain model ownership. The CPU negative control detects old serialization. Real-model matched greedy and seed-193 runs preserve exact tokens, Unicode/literal text, rendering and restored continuation. V7 metadata waits were 4.406–4.767 seconds; candidate replies completed during generation in 0.657–1.909 ms. This measures short-context contention, not GPU throughput. Source/package hashes and negative control are in metadata-concurrency-20261019; real-model-v2/result.json records qualification and production restoration, with minimum available RAM 60.38 GB. Activation preserves agent PIDs/sessions/spend, authority and compatible RAM caches; source and installed config change only executable. Metadata never serves as a model barrier.

src/models/qwen/hip/model_loader.cpp copies GGUF regions into anonymous mmap storage, advises MADV_HUGEPAGE before population and registers the immutable copy read-only with HIP. These non-reclaimable weights require separate dashboard accounting from llama's file-backed mapping; host headroom uses MemAvailable.

Native policy preserves learned draft length across chunks/restores. PrepareContinuation reattaches the token index without starting a new request; pending-token consumption updates physical and logical history once. Native replay verified sampled continuation, tools and reasoning closure, with speed neutral (draft-policy-continuation-20261019-v3).

CointOS owns bounded steps/accounting. DFlash's published but unconsumed token is consumed before publishing a completed step. Gufo decodes from an equal complete vector; llama needs strict extension. Per-backend can_continue governs lanes/snapshots. Treating equality as divergence caused per-chunk restores despite identical histories. Regressions cover the Python integration; direct-native qualification missed it. The fix is live: 46.4 seconds showed zero false divergences with agent/Coin/native PIDs preserved (gufo-equal-prefix-20261019/{activation.json,summary.json}). Snapshots bind target/draft identity, policy, revision, ABI, context, protocol, sampler history/RNG and checksums. Save serializes directly into an anonymous mapped file, avoiding full host staging. OpenSSL EVP SHA-256 covers header/payload on save and is checked before restore; sync/publication follow serialization. Immutable GPU snapshot copies still cost memory (patches/gufo/control.cpp). Gufo/llama caches have separate private user-owned directories.

Persistent tensors omit the request-local token index: RestorePersistentSnapshot requires PrepareContinuation before prompt extension. Restore reuses the physical executor after Invalidate clears transient state. Recreating full target/draft allocations at each switch caused avoidable churn; a failed destructive restore leaves the lane empty. Cold starts still allocate. Native regression and real continuation tests cover these contracts.

Compatible daemon replacement adopts an independent model scope; a new session alone inherits daemon cgroup cleanup. Warm restored state and settle PSI/headroom before daemon adoption/thaw; keep the guard intact. The benchmark procedure owns kernel-confirmed client freezing when systemd notifications are unreliable.

V5 qualification ~/.local/state/cointos/gufo-dflash-reuse-qualification-20261018-v2 verifies partial-prefix extension, sampled overwrite/disk/process continuation, tool-call/result replay, reasoning closure and five exact restores at 130,944 tokens. Full restores took 4.74–4.78 seconds; minimum available memory was 42.3 GB against a 24 GB reserve. Its 945-test Python qualification had three skips; CPU/HIP tests pass.

metadata-concurrency-20261019/activation/verified.json binds the previous V8 metadata binary and its build-time Python adapters. live-summary.json records 61.08 seconds with 536 generated tokens, maximum text/tokenize latency 0.882/1.124 ms, minimum available RAM 45.4 GB, PSI ≤0.01 and no guard/drain/pause. This verifies live responsiveness and resumed work, not a matched throughput speedup.

Installed configuration: 32 tokens/10 seconds; source: 32/30. Verify effective values through the daemon. Two existing dependency/recovery check categories remain. The Qwen measurement owner separates short fixtures from loaded long-context rates; sustained factory throughput remains unproved.

Proof:

```bash
python3 -m unittest tests.test_gufo_qualification tests.test_backend tests.test_backend_gufo tests.test_reasoning_budget
```
