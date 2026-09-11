# Subsystem health: MVP disposition

Reorganized by Astra (Codex `/root`), 2026-09-05, at David's request to strip the existing plans down and extend them into complete MVP bring-up.

**Status:** historical plan replaced by a proposed execution suite, pending David's approval. This page preserves the previous link and remaining obligations; it is not a second executable plan or a claim of live readiness.

**Start here:** [CointOS MVP index](2026-09-05-cointos-mvp-index.md) and [complete design](../specs/2026-09-05-cointos-mvp-design.md).

Use one small deterministic health catalogue, one incident reducer and bounded repair independent of the ordinary scheduler. Small and large model inspectors are prioritized resource-admitted jobs, not mandatory verdicts on every heartbeat.

**Current task owners:** H1-H5; R3/R7; P2-P4 for proposed repair activation.

Retain boot-bound observation freshness, observed process/endpoint/progress facts, deduplicated incidents, bounded repair attempts and independent recovery proof. A candidate_ready result is not an activated repair and cannot close the incident; proposed changes require exact Coin approval.

The three operating principles remain Coin availability, no OOM and seamless dynamic-context handovers. Keep correct obligations, evidence and narrow sound mechanisms; delete false decompositions at the owning implementation task. Deferred hardening has one queue in the new index. No services, runtime state, credentials or code were changed by this planning replacement.
