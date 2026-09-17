---
scope: project local
status: "unverified"
source: "2026-09-17 coordinator reconciliation of Git, installed assets, live systemd units, focused checks, and owning KT leaves"
review_when: Update after material repository, installation, or live-service changes.
updated_at: "2026-09-17T13:39:02+10:00"
---

Development is on branch `docs/cointos-mvp-bringup`. Executor-service restart recovery and the qualified 100 GiB capacity correction are committed and pushed. Backend-instance restart reconciliation and physical-capacity policy deduplication are installed, qualified, and pending commit. Services execute the installed copy.

Automatic inference acquisition covers fresh capacity routing, unloaded-model realization, idle residency reclamation, priority-aware allocation, terminal tool-boundary park/reacquire, dead-owner ghost reconciliation, context-overflow rerouting, exact retained-session continuation, executor-service restart recovery, and old-backend-instance termination evidence after Lemonade restart. The cancelled `ReservePolicyDeduplicator` reached terminal `cancelled` after installed reconciliation released its worker and inference allocations.

The machine's qualified GPU allocation capacity is 100 GiB. The 64 GiB `mem_info_gtt_total` value remains an informational sysfs-domain observation; it does not reduce capacity. The 32 GiB protected-host, 8 GiB control, 12 GiB load-transient, and 100 GiB GTT boundary now exist only under `physical_capacity`; inference scheduling merges those values with sequence, lease, proxy, and residency settings from `inference_capacity`.

Sudden-agent-death protections include a 32000-token managed-worker output reserve, exact backend/client capacity checks, retained-session continuation, unlimited ordinary task budgets, and recovery after executor or backend restart. A newly observed scheduler defect remains: repeated retained-session prefill can consume each 300-second fairness slice before useful progress, causing indefinite redispatch. Automatic verifier spawning also remains an unnecessary production-work competitor.

Focused evidence: source compilation; 144 existing inference-capacity, enforcement, operator-inference, managed-inference, and executor tests; installed zero-duplicate policy inspection; successful stranded-worker cancellation reconciliation; and five persistent services running. No new regression test was added.
