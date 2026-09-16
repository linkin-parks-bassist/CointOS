---
scope: project local
source: "David dispatch-barrier policy correction and implemented OpenCode version behavior 2026-09-15"
review_when: Recheck when scheduling architecture changes or an implementation is accepted.
status: "unverified"
updated_at: "2026-09-15T22:09:32+10:00"
---

CointOS schedules durable logical agents over finite physical GPU execution slots while treating this host's verified 128 GB-class unified-memory capacity as abundant, as specified by `what/is/the/local/strix/halo/resource/policy.md`. Agent identity, context capacity, backend request, physical slot,
and model residency are distinct: more agents may wait or receive less service, but
must not silently receive smaller contexts. Priority and measured accelerator
service govern scheduling while eligible lower-priority work continues to progress.

The canonical post-MVP switching model is to preserve complete compatible inference
state, release physical occupancy, and later restore that state without replaying
the full prompt. Disk, RAM, and GPU are residency tiers; immutable model weights may
be shared. This architecture is accepted intent, not proof that the current runtime
implements it. For now local Qwen dispatch is manually serialized as documented in
the global local-agent launch procedure.

David restoration priority 2026-09-14: first recover useful bounded live parallelism with managed allocation and accurate OpenCode limits. Exact native inference-state switching is not a prerequisite for this milestone. Two agents must actually make concurrent progress; excess work queues, cleanup verifies resource release, and no promised context shrinks silently. The previous manually serialized practice is historical baseline, not the current target. See `what/is/the/plan.md`.

## Priority and automatic resource acquisition

David clarification 2026-09-14: inference acquisition must be automatic and easy. Reject a request only when it is suspicious/unauthorized, or when actual physical resources cannot satisfy it after applying priority and reclaiming lower-priority allocations. Ordinary contention produces waiting or suspension, not a terminal denial.

Priority order is sole survivor, Cointelprofessional, user agent sessions, then background work under the existing health/fairness bands. These first three classes should practically never be denied service due to lower-priority blockers: suspend those blockers, preserve their durable tasks/sessions and resume them later. Do not kill their logical work or discard recovery state. Equal/higher-priority contention waits according to policy; no scheduler can promise simultaneous service beyond physical capacity.

Identity and priority come from the authenticated/trusted launch or control boundary, not a caller's self-declared role string. Internal allocation records and credentials remain bookkeeping the system obtains, renews and cleans up; operators and agents do not manually negotiate leases. Missing internal paperwork, stale observations or an unfamiliar client version are repair work for CointOS, not evidence that a benign request is suspicious. Package-version identity never gates dispatch; optional measured client ceilings refine live backend and configured output bounds in the background. Queue while genuinely necessary facts refresh, preserve the request, and wake it automatically. Never invent capacity or silently reduce promised context.

Suspension must release verified physical occupancy before its replacement launches. Retained OpenCode sessions and ordinary recovery are sufficient for the first implementation; exact native inference snapshots remain a separate later goal. Resume displaced lower-priority work when higher-priority demand subsides and preserve fair progress.

David’s scheduling idea (2026-09-15, design exploration): tool calls can act like syscall/yield boundaries. A logical agent may remain active while it waits for tools and has no GPU demand; those resources should serve other ready requests and the agent should queue/reacquire for its next inference call. This is an analogy, not a mandate to context-switch on every tool call. The current bounded MVP task targets inference-call boundaries, with reasonable availability propagation and no false-unavailability denial. Model/cache residency may stay warm when no other demand needs reclamation. Full native KV context switching remains the separate post-MVP goal above.
