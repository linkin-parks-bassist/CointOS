---
scope: project local
status: "unverified"
source: "2026-09-17 reconciliation of current implementation, live services, defect owners, and David's active priorities"
review_when: Recheck after each completed item or priority change.
updated_at: "2026-09-17T13:39:02+10:00"
---

1. Remove unconditional ordinary-task verifier spawning. Successful ordinary MVP tasks should complete directly; retain independent verification only through explicit task/operator intent, and stop the watchdog from manufacturing unrequested verifier work.
2. Fix retained-session prefill/time-slice livelock so a resumed worker receives enough productive execution to cross prefill and make progress. Account for measured prefill or gate fairness preemption on a progress boundary.
3. Measure the remaining 32 GiB protected-host, 8 GiB control, and 12 GiB load-transient reserves against live pressure and actual model loads; adjust values only from evidence.
4. Measure legitimate maximum-context traffic against proxy transport ceilings and derive or raise any ceiling that can truncate valid work.
5. Continue Cointelprofessional answer verification and the chunking/dissolution pipeline after the scheduler defects above are closed.

The 64 GiB sysfs-domain observation no longer caps the qualified 100 GiB hardware boundary. Physical reserve fields now have the single owner `physical_capacity`. Backend restart reconciliation and cancellation cleanup are installed and live-qualified. Use one observable Qwen worker at a time for small concrete slices; keep source, installation, and these spine leaves synchronized.
