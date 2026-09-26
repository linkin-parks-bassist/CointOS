---
status: green
revised_at: "2026-09-26T09:53:51+10:00"
---

The plan is to reach the system defined in `what/is/cointos.md`: an autonomous, self-sustaining agent ecosystem that keeps the GPU busy with useful work without David's prompting.

**Milestone 1: autonomy loop (current).** Build on the existing scheduler rather than hardening it further:
- write the steward/manager/worker role classes; *(done, e888d61)*
- put work queues in knowledge trees; *(done, in use)*
- give Coin knowledge-tree tools; *(done, live check pending)*
- add a spawner that starts an agent whenever capacity is free. *(built and enabled, e888d61; first live cycle unobserved)*

Acceptance is judged by observation: left alone, the GPU stays busy, drafted ideas and queued work visibly advance in their repositories under `~/Projects/`, and the system does not fall over. The concrete steps are in `what/is/next.md`.

**Milestone 2: stability and recovery.** Once agents are running continuously, fix what actually breaks under real load. Prove Sole Survivor recovery on a real or safely induced incident, and keep Coin essentially always available. Scheduler follow-ups (sibling cancellation, pressure priority, multi-model selection, MTP throughput, proxy transport limits, lease archival) are done only when real load shows they matter.

**Milestone 3: the idea pipeline and role diversification.** Deepen the dissolution pipeline (`what/is/architecture/of/cointos.md`): multi-step chunking, review and audit at the right abstraction levels, and diversified roles within each class.

**Standing constraints.**
- No named Qwen model or fixed slot count defines capacity; resident allocation, durable demand, policy, headroom and evidence-backed ceilings do.
- Physical llama.cpp `--parallel` changes need unload/load and may lose KV cache.
- Keep user runtime under `~/.CointOS`; the root survival plane is a separate boundary.
- Only side-effect-free, subsecond predicates belong in knowledge-tree startup proofs.
- Executor distillation criteria are in `how/should/executor/py/be/fractionally/distilled.md`; do not split files cosmetically.
