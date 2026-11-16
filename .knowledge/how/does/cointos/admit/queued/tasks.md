---
status: green
revised_at: "2026-11-07T11:47:01+11:00"
---

tasks.create allocates tasks in the shared task/queue namespace. schema.KINDS owns role, rank, scope and receipt/landing vocabulary. lifecycle.py owns transitions and acceptance; frontier.py derives recovery ownership from current work. A failed assignment goes directly to one capable controller, with no decomposition-manager stage. Automatic controllers in the same project execute serially; unrelated workers and independent review remain eligible.

Spawner refreshes work/dependency projections and materializes current recovery before choosing retained runnable tasks by rank/creation time. It then considers new queue work, integrations, maintenance and scouts. Admission and GPU pre-emption are separate. Resource admission uses capacity.py's shared process/native-state commitments before launching, with disposable cache reclamation; how/does/cointos/protect/workstation/memory.md owns the capacity contract. Ordinary dependency waits remain valid; user holds, disabled projects, stale ownership and active same-project integration govern eligibility.

Pending typed test corrections are derived admission prerequisites for consumers of the original packet. A brief revision cannot restart those consumers early. The author never waits on its own correction; waiting consumer reviews cannot occupy the correction's review slot. Withdrawal removes this wait without changing old acceptance; independent acceptance refreshes dependent assignments. Runtime queue projections identify the pending correction. Already active runs retain ordinary lifecycle handling. This behavior is installed. The 132-test isolated installed replay covers the race and reviewer ordering; live-ledger inspection confirms consumer admission waits while correction review remains eligible. Native acceptance of correction 53e6a913 then advanced the unchanged implementation to version 5 and launched worker-6293c0; its own task tool returned that corrected binding and no pending correction.

Exclusive run-directory reservation and lock-gated admission preserve task/run/key ownership. Adoption follows exact current task or receipt identities; missing/displaced unreceipted runs fail into First Responder diagnosis, and receipted survivors are watched until exit.

A run engages on its first admitted gateway thought. Unexpected exits before or after that point fail immediately into First Responder recovery for every role; launch-failure counts remain diagnostics, without automatic retries or new holds. Missing runs after restart also require diagnosis. Explicit cancellation withdraws work and suppresses recovery; Pause and Hold remain distinct controls. Workers with split_supervisor are ineligible for admission until the mandatory split hands off, even after its failed Supervisor's hold clears.

Names/launch, GPU scheduling, completion, queue revision, history and reviewed test corrections retain their focused owners. Source implementation and installed acceptance are separate.
