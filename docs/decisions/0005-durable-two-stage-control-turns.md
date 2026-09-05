# 0005: Durable two-stage Telegram control turns

Status: accepted 2026-09-04; residency and scheduling portions superseded by 0006.

## Context

Telegram polling previously performed a complete Qwen control/tool loop and model-
generated notification presentation inline. Under model load, one message blocked
receipt of every later update for minutes. Conversation receipt was written only
after completion, so the five-minute fallback appeared mistimed and crashes could
replay tool actions. A quick canned acknowledgement would hide rather than repair
those failures.

## Decision

Represent every admitted Telegram update as one durable, deduplicated control-turn
record before inference. The transport then asks resident GLM for one small generated
first response using bounded recent context. It records attempt, generation, send,
and delivery separately and never substitutes canned prose on model failure.

Independent supervised workers claim durable turns and run capable Qwen deep control
outside the polling path. Deep control uses typed terminal tools to either publish
material new information or finish silently, preventing a second acknowledgement.
Action results are cached per turn, and queued work has a deterministic idempotency
key. Result notification presentation runs in a third process so it cannot stall
intake. Delivery interrupted at an unknowable point is recorded explicitly rather
than blindly replayed.

The literal disaster response remains transport-owned and is eligible only after
300 seconds without a known generated delivery. GLM, Qwen3.8-27B, and Coder-30B are
the three intended boot-resident models. Qwen's aggregate context is 262,144 tokens
across four request sequences.

## Consequences

New messages remain responsive while earlier deep turns use tools or wait on Qwen.
Receipt and response latency are now auditable facts. Two deep turns may run in
parallel, bounded by service configuration. Telegram itself offers no idempotency key
for `sendMessage`, so a process death during an in-flight send is truthfully marked
`delivery_unknown` and is not automatically replayed.
