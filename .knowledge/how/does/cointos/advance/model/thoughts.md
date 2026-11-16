---
status: green
revised_at: "2026-11-17T10:07:54+11:00"
---

An agent is waiting, reading, reasoning, writing or running a tool. Reading/reasoning/writing require a lane; tools do not.

A thought advances in bounded steps: up to `read_chunk_tokens` while establishing context, then up to `chunk_tokens` while generating. Scheduling decisions occur between steps; a running backend request is not torn in half.

During a generation step, Gufo streams each selected token and its raw decoded piece over the control socket before returning the step result. `lanes.arrived` decodes those bytes incrementally across steps, queues token/text fragments, and the gateway sends each text delta to OpenCode while dashboard live words repaint at 10 Hz. For Halogen, the adapter instead publishes the complete validated token vector at step end; its current 8-token steps trade boundary overhead for smoother delivery. The Halogen integration owner holds timing evidence. The step remains the scheduling and pre-emption boundary.

Gufo receives the read-step budget as max_input_tokens. Control::Prefill rejects an extension larger than that budget and loops until native progress consumes the requested suffix. The Qwen runner separately caps each inner batch at QwenGpuArena::GetMaxBatch, 4,096 in pinned arena.cpp; an outer request can contain several inner batches. Current CointOS read steps are 1,024, so they cannot exercise a 4,096-row inner batch. Increasing the read budget may improve batching but lengthens an uninterruptible backend call. No gain is established: qualify matched prompt work, continuation correctness, memory and foreground blocking before changing it. Evidence: backend_gufo.prefill, patches/gufo/control.cpp and pinned Gufo inference_backend.cpp/hip/arena.cpp.

At each boundary:

1. Coin takes precedence at completed steps, including over background reads and tool grace. Other requests compete by a local priority-weighted random draw without usage history or debt. request_class may demote Coin without changing ownership; elevation is refused. A generating holder is displaced before a reader when possible.
2. Peer slices and unsaved reads remain protected; checkpointed/resident partial reads may yield after the slice expires. The scheduler procedure owns clocks and eligibility.
3. A tool call yields the lane. A bounded grace may retain it for a quick follow-up within the same unexpired slice; grace never extends the slice.
4. Placement prefers the agent's held lane, then a warm lane, then a free lane, then an eligible unreserved lane. Warmth uses each backend's can_continue contract: Gufo accepts an identical complete vector; llama requires extension. Equality is not divergence.

lanes.py advances thoughts at these boundaries. The local weighted-lottery policy, clocks and checkpoint eligibility retain how/does/the/cointos/scheduler/share/a/lane/among/equal/agents.md. Native validation retains how/does/cointos/validate/model/token/state.md.
