# Foundation stabilization: MVP disposition

Reorganized by Astra (Codex `/root`), 2026-09-05, at David's request to strip the existing plans down and extend them into complete MVP bring-up.

**Status:** historical plan replaced by a proposed execution suite, pending David's approval. This page preserves the previous link and remaining obligations; it is not a second executable plan or a claim of live readiness.

**Start here:** [CointOS MVP index](2026-09-05-cointos-mvp-index.md) and [complete design](../specs/2026-09-05-cointos-mvp-design.md).

Use R1-R7 for the remaining admission, resource, scheduling, context and recovery work. Do not repeat completed repairs or preserve an incompatible scheduler because old tests encode it.

**Current task owners:** R1-R7; C2/C5 for actual front availability.

Retain loaded/backend-alive busy-model truth, separate pressure from actual OOM, durable effect postconditions, one survivor and independent restrictive gates. Resource recovery must not restart the permanent contact/notification route in a storm. The observed Lemonade management health endpoint was http://127.0.0.1:13305/api/v1/health (the previous 8000 value was corrected); production consumes configured endpoint facts, not this historical literal.

The three operating principles remain Coin availability, no OOM and seamless dynamic-context handovers. Keep correct obligations, evidence and narrow sound mechanisms; delete false decompositions at the owning implementation task. Deferred hardening has one queue in the new index. No services, runtime state, credentials or code were changed by this planning replacement.
