---
scope: project local
status: "unverified"
source: "2026-09-17 reconciliation of current implementation, live services, defect owners, and David's active priorities"
review_when: Recheck after each completed item or priority change.
updated_at: "2026-09-17T13:41:36+10:00"
---

1. Fix retained-session prefill/time-slice livelock so a resumed worker receives enough productive execution to cross prefill and make progress. Account for measured prefill or gate fairness preemption on a progress boundary.
2. Measure the remaining 32 GiB protected-host, 8 GiB control, and 12 GiB load-transient reserves against live pressure and actual model loads; adjust values only from evidence.
3. Measure legitimate maximum-context traffic against proxy transport ceilings and derive or raise any ceiling that can truncate valid work.
4. Continue Cointelprofessional answer verification and the chunking/dissolution pipeline after the scheduler defect above is closed.

Ordinary successful tasks now complete directly; independent verification is explicit through `verification_requested=True` or `ecosystem enqueue --verify`. The 64 GiB sysfs observation does not cap the qualified 100 GiB hardware boundary, and physical reserve fields have one configuration owner.
