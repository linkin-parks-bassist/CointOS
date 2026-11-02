---
status: green
revised_at: "2026-10-31T16:34:42+11:00"
---

Tubo (https://github.com/BonkusCheemus/tubo) is a public Gufo fork targeting Qwen3.8-27B on gfx1151. At inspected commit 17232b3ad79e591dc24af53a4346a4f46d488ca0, its README reports a same-laptop UD-Q4_K_XL/DFlash2/fp16-KV comparison of 29.6 versus 37.8 tokens/s. This is publisher evidence on a Ryzen MAX+392 32 GB laptop at pinned clocks, not a local result or a >60 tokens/s mixed-work qualification.

Potential same-model candidates include batched/fused small verification projections and draft/selector routes. The publisher reports those paths as bitwise equal in its tests. Verify code, arithmetic, compiler behavior and full native continuation locally before reusing them. Its newer upstream base and altered cache state mean a drop-in replacement is unqualified for CointOS's resident per-agent state and snapshot contracts.

The README distinguishes changed-numerics options: its apex weights are a different fine-tune/quantization; Turbo6 KV is lossy; fast mode can change output; the IQ3 path fails its own quality threshold. Those results do not establish performance for the user-fixed canonical Qwen model. Q4/Q5/Q6/IQ4 band-kernel bandwidth figures are microbenchmarks, explicitly not wired into its serving path. The fork is a research lead only; nothing from it is installed.

Its independent EVO-X2 64 GB report (docs/models/qwen3.8-27b/INDEPENDENT_EVO-X2_2026-10-28.md) records much smaller same-fp16-KV gains on the upstream benchmark, around +3.9% mixed and −3.9% repetitive. Short greedy coding can reach around 60; a ~30.6K prompt reports 33.9 versus 46.1 tokens/s with lossy Turbo6 plus draft flags. Those are different workloads/settings, not local sustained >60 evidence.

A concrete same-byte research lead is GUFO_DEV_WEIGHTS_GTT: model_loader.cpp copies immutable weights with hipMalloc, double-buffered 64 MiB pinned staging and source-page reclamation. Current CointOS instead registers anonymous huge-page host copies. Compare complete mapped-versus-driver-owned weight traffic, startup, memory headroom, exact tokens and snapshots before adopting a placement change. Other inspected leads are fused small verification projections and avoiding host synchronization/feature copies. NPU remains deferred.
