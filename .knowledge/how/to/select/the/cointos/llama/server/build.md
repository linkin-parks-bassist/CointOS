---
status: green
revised_at: "2026-11-16T15:13:28+11:00"
---

Verify the actual executable/version through Lemonade health/launch arguments and binary hashes; configuration success alone does not establish what ran. Record and restore the previous selector for isolated comparisons. Lemonade is 2026.46.2; the older selector procedure needs live-version verification.

The active Vulkan selector is `/opt/cointos-llama-state-size/1a24df163-v1/bin/llama-server`: b11846/1a24df163 with the native size-query patch. It copies the packaged launcher, uses a separately built server implementation with matching embedded UI, and pins copies of the matching core libraries beside it. Requalify before intentionally upgrading the bundle. `patches/llama-state-size/` owns the patch, CMake build and guarded installer. GET /slots exposes state_size_bytes only for an idle target-only slot, counting the actual file format and recurrent checkpoint appendix. Synthetic CPU files matched at 5,420 and 95,292 bytes; Flash's 927-token file matched at 736,762,924 bytes. Evidence: ~/.local/state/qwen-flash-diagnosis/native-size-{qualification,hybrid-qualification}.json. Rollback: lemonade config set llamacpp.vulkan_bin=builtin; this reloads the model. The original packaged binary remains under /var/cache/lemonade/bin/llamacpp/vulkan. Lemonade serves Flash-Next on one 128k slot without speculation; model facts owns the live shape. The earlier static d493f84 DSpine server/hash and packaged dbe4c3ed4 describe retained trial builds, not the current executable. The DSpine and steering owners preserve trial qualification.

The former `/tmp/opencode/llama-dspine` checkout and its static/HIP candidate paths are absent. A fresh private checkout of `Ajay9o9/llama.cpp` branch `dspine` is at `/home/david/Projects/qwen-weight-codec/vendor/llama-cpp`, pinned to `d493f841b20241606c47a4e0537d3c786b5cf50b`. Its standalone Vulkan build in `/home/david/Projects/qwen-weight-codec/build-vulkan/bin/` successfully builds llama-server and llama-bench; it was not deployed or used as the timing control for the separate Triton exact-compression probe. Matching source revision does not imply byte-identical builds or qualification of changed options.

The earlier `/opt/cointos-llama-stop-010be9683/explicit-continuation/llama-server` bundle is absent. Its earlier qualification does not establish current behavior. Retained b10723 patches cover speculative-stop handling, paired MTP snapshots and explicit continuation. Review them against current source before reuse; their presence and target-token retention do not establish current draft-state preservation. Save/restore counts alone do not establish identical continuation.

The current Lemonade unit has ProtectHome=yes and PrivateTmp off. Home and host /tmp builds are unsuitable service deployment paths. Public user model copies support standalone experiments; verify their hashes against live weights. Do not silently replace the server or install an unqualified historical binary.

The isolated HIP candidate was built from d493f84 with TheRock SDK `/var/cache/lemonade/bin/therock/gfx1151-7.14.0`; its former `/tmp` binary is unavailable. To recreate a private build, set `src` and `build` to the checkout and output directory:

```bash
sdk=/var/cache/lemonade/bin/therock/gfx1151-7.14.0
ROCM_PATH="$sdk" cmake -S "$src" -B "$build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_HIP=ON -DGGML_VULKAN=OFF -DCMAKE_HIP_COMPILER="$sdk/llvm/bin/clang++" -DCMAKE_HIP_COMPILER_ROCM_ROOT="$sdk" -DAMDGPU_TARGETS=gfx1151 -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_CURL=OFF
cmake --build "$build" --target llama-server -j 2
```

That recipe previously built and ran on Radeon8060S; the fresh compression workspace has only built Vulkan. HIP/hipBLAS/rocBLAS still resolve to SDK shared libraries despite static llama/ggml linkage, so preserve service accessibility. Short-prefix speed evidence does not qualify resident shape, continuation or useful outputs. The DSpine owner holds measurements and the unqualified proposal-shaping variant; keep baseline and candidate binaries separate.
