# 0006: Survival-first model and context scheduling

Status: accepted, 2026-09-04.

## Context

The previous resident-model policy allowed multiple large pinned models and admitted
a 51.8 GiB FP16 vLLM model despite only 11.5 GiB available host memory and 80.5 GiB
of Radeon GTT already in use. The prior boot recorded 58 OOM kills. GNOME and chatbot
processes died while inference survived. Long agent contexts also repeatedly reached
hard backend limits and failed without a planned continuity transition.

Lemonade can pause its own job abstraction but ordinary OpenAI-compatible OpenCode
requests are not Lemonade jobs. It also does not expose serialization of live backend
KV caches. OpenCode does provide durable sessions, exact JSONL events, and token usage.

## Decision

Machine responsiveness outranks inference throughput. Bound TTM to 64 GiB, contain
Lemonade in a low-priority inference slice, protect interactive/control services, and
watch OOM count, available memory, swap, PSI, and GTT each second.

Pin only Qwen3.5 4B for chatbot, routing, and emergency control. Permit at most one
additional unpinned work model. For each spawned agent and again before dispatch,
the pinned model chooses `use_loaded`, `load`, or `defer`, a target model, and a
generous context allocation from mechanically prevalidated choices. Caller model
choices are hints. Deterministic validation retains authority over model existence,
role compatibility, residency count, host/GTT reserve, and context safety. Prefer a
compatible loaded large model for new smaller work.

Run OpenCode in a process group. Higher-priority work preempts lower-priority work,
and equal-priority work rotates after five minutes. Preserve the OpenCode session,
prompt, log, job state, and filesystem boundary. At 75% of the allocated context,
resume the old session only to create a semantic handoff, archive its log, and carry
on in a fresh session. A missing semantic handoff becomes a visibly degraded
mechanical recovery artifact.

Any increment in the kernel OOM counter latches emergency mode: record the incident,
checkpoint running work, stop inference clients, unload every model, reload only the
small control model, and dispatch exactly one `sole_survivor`. No ordinary work may
run until that exact role requests recovery and the deterministic health gate passes.
Pre-OOM pressure similarly interrupts work and unloads dynamic models, but preserves
the chatbot and automatically resumes after a sustained healthy interval.

## Consequences

Large models remain legal, but residency and context are dynamic leases rather than
boot assumptions. Routing itself can fail, so invalid output explicitly defers work.
The small model was chosen empirically: constrained routing JSON took about 0.7
seconds versus repeated multi-second hidden-reasoning truncation from DeepSeek-Qwen3
8B. A live 30B job with a router-selected 131,072-token context left the workstation
healthy and the pinned chatbot answered a contention probe in about 1.1 seconds.

Continuity is strong but not bit-identical: the system preserves semantic/durable
agent state, not backend KV cache tensors. Context memory is conservatively estimated;
observed pressure and the hard TTM boundary remain authoritative.
