---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local
source: docs/decisions/0016-concurrent-inference-and-residency-timesharing.md; docs/decisions/0019-saved-state-timesharing-after-poc.md; David clarifications 2026-09-11
verification: Read both accepted decisions and separated intended architecture from current runtime practice.
review_when: Recheck when scheduling architecture changes or an implementation is accepted.
---

CointOS is intended to schedule durable logical agents over scarcer physical GPU
execution slots. Agent identity, context capacity, backend request, physical slot,
and model residency are distinct: more agents may wait or receive less service, but
must not silently receive smaller contexts. Priority and measured accelerator
service govern scheduling while eligible lower-priority work continues to progress.

The canonical post-MVP switching model is to preserve complete compatible inference
state, release physical occupancy, and later restore that state without replaying
the full prompt. Disk, RAM, and GPU are residency tiers; immutable model weights may
be shared. This architecture is accepted intent, not proof that the current runtime
implements it. For now local Qwen dispatch is manually serialized as documented in
the global local-agent launch procedure.
