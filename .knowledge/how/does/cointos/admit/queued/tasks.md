---
status: green
revised_at: "2026-10-16T05:23:05+11:00"
---

tasks.create allocates tasks in the shared task/queue namespace. schema.KINDS owns role, rank, scope and receipt/landing vocabulary. lifecycle.py owns transitions and acceptance; frontier.py derives recovery ownership from current work. A failed assignment goes directly to one capable controller, with no decomposition-manager stage. Automatic controllers in the same project execute serially; unrelated workers and independent review remain eligible.

Spawner refreshes work/dependency projections and materializes current recovery before choosing retained runnable tasks by rank/creation time. It then considers new queue work, integrations, maintenance and scouts. Admission and GPU pre-emption are separate. Ordinary dependency waits remain valid; user holds, disabled projects, stale ownership and active same-project integration govern eligibility.

Pending typed test corrections are derived admission prerequisites for consumers of the original packet. A brief revision cannot restart those consumers early. The author never waits on its own correction; waiting consumer reviews cannot occupy the correction's review slot. Withdrawal removes this wait without changing old acceptance; independent acceptance refreshes dependent assignments. Runtime queue projections identify the pending correction. Already active runs retain ordinary lifecycle handling. This behavior is installed. The 132-test isolated installed replay covers the race and reviewer ordering; live-ledger inspection confirms consumer admission waits while correction review remains eligible. Native acceptance of correction 53e6a913 then advanced the unchanged implementation to version 5 and launched worker-6293c0; its own task tool returned that corrected binding and no pending correction.

Exclusive run-directory reservation and lock-gated admission preserve task/run/key ownership. Adoption follows exact current task or receipt identities; displaced tasks requeue and receipted survivors are watched until exit.

A run engages on its first admitted gateway thought. Earlier exit is an infrastructure launch failure: its attempt is refunded, consecutive failures are separately bounded, and repeated failure creates a durable admission hold and recovery obligation. The controller can release that hold after repair through typed resume. Explicit user holds require user release. An engaged unreceipted exit follows bounded execution recovery.

Names/launch, GPU scheduling, completion, queue revision, history and reviewed test corrections retain their focused owners. Source implementation and installed acceptance are separate.
