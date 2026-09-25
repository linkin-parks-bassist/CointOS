---
status: green
revised_at: "2026-09-26T08:12:29+10:00"
checked_at: "2026-09-11T18:43:14+10:00"
---

The survival plane is a model-independent, root-owned boundary for authenticated
contact ingress, lifecycle control, critical reporting, and recovery when ordinary
orchestration is unhealthy. Its gateway, guardian, and unprivileged checkpoint
consumer have separate identities and filesystem authority. Requests, phase
transitions, attempts, results, and incidents are durable and replay-safe; ambiguous
external delivery is reported as unknown, never silently retried as safe.

Lifecycle commands advance only after observed postconditions. A Sole Survivor failure is an escalation trigger, not a terminal steady state or a reason to wait for David to notice; successor recovery agents remain dedicated to diagnosis and repair, with durable identity, evidence, and backoff. Recovery remains
restrictive until required services, model health, job reconciliation, and previous
activation/pause state are independently established. Kernel OOM increments are
immediate emergencies; non-OOM pressure requires sustained evidence. Root-owned
survival controls must not be emulated through ordinary user services. Intended
architecture and checked-in code do not establish live activation.
