---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local
source: git show fe92546:docs/specs/2026-09-04-cointelprofessional-survival-control-design.md; git show fe92546:docs/specs/2026-09-05-cointelprofessional-survival-closure-design.md; current survival code
verification: Distilled stable boundaries and excluded historical incident chronology and unaccepted deployment claims.
review_when: Recheck after survival-plane activation, lifecycle-schema changes, or resource-control redesign.
---

The survival plane is a model-independent, root-owned boundary for authenticated
contact ingress, lifecycle control, critical reporting, and recovery when ordinary
orchestration is unhealthy. Its gateway, guardian, and unprivileged checkpoint
consumer have separate identities and filesystem authority. Requests, phase
transitions, attempts, results, and incidents are durable and replay-safe; ambiguous
external delivery is reported as unknown, never silently retried as safe.

Lifecycle commands advance only after observed postconditions. Recovery remains
restrictive until required services, model health, job reconciliation, and previous
activation/pause state are independently established. Kernel OOM increments are
immediate emergencies; non-OOM pressure requires sustained evidence. Root-owned
survival controls must not be emulated through ordinary user services. Intended
architecture and checked-in code do not establish live activation.
