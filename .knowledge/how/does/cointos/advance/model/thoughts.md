---
status: green
revised_at: "2026-10-19T19:32:47+11:00"
---

An agent is waiting, reading, reasoning, writing or running a tool. Reading/reasoning/writing require a lane; tools do not.

A thought advances in bounded steps: up to `read_chunk_tokens` while establishing context, then up to `chunk_tokens` while generating. Scheduling decisions occur between steps; a running backend request is not torn in half.

Gufo receives the read-step budget as max_input_tokens. Control::Prefill rejects an extension larger than that budget and loops until native progress consumes the requested suffix. The Qwen runner separately caps each inner batch at QwenGpuArena::GetMaxBatch, 4,096 in pinned arena.cpp; an outer request can contain several inner batches. Current CointOS read steps are 1,024, so they cannot exercise a 4,096-row inner batch. Increasing the read budget may improve batching but lengthens an uninterruptible backend call. No gain is established: qualify matched prompt work, continuation correctness, memory and foreground blocking before changing it. Evidence: backend_gufo.prefill, patches/gufo/control.cpp and pinned Gufo inference_backend.cpp/hip/arena.cpp.

At each boundary:

1. Higher-class work pre-empts lower-class work. Direct Coin requests outrank user sessions, which outrank background work. request_class can demote a request without changing ownership; priority elevation is refused. A generating holder is displaced before a reading holder when possible.
2. Checkpointed reads and generation share a weighted lottery; unsaved reads stay protected. The scheduler procedure owns clocks and eligibility.
3. A tool call yields the lane. A bounded grace may retain it for a quick follow-up within the same unexpired slice; grace never extends the slice.
4. Placement prefers the agent's held lane, then a warm lane, then a free lane, then an eligible unreserved lane. Warmth uses each backend's can_continue contract: Gufo accepts an identical complete vector; llama requires extension. Equality is not divergence.

lanes.py advances thoughts at these boundaries. The equal-class lottery, clocks and checkpoint eligibility retain how/does/the/cointos/scheduler/share/a/lane/among/equal/agents.md. Native validation retains how/does/cointos/validate/model/token/state.md.
