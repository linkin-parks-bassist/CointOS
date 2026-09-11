# Survival closure: MVP disposition

Reorganized by Astra (Codex `/root`), 2026-09-05, at David's request to strip the existing plans down and extend them into complete MVP bring-up.

**Status:** historical plan replaced by a proposed execution suite, pending David's approval. This page preserves the previous link and remaining obligations; it is not a second executable plan or a claim of live readiness.

**Start here:** [CointOS MVP index](2026-09-05-cointos-mvp-index.md) and [complete design](../specs/2026-09-05-cointos-mvp-design.md).

Keep load-bearing correctness obligations but remove the exhaustive closure-before-online gate. C4 offline composition and C5 bounded live acceptance now establish the first usable installation.

**Current task owners:** C4-C5; H2-H3; P3-P4.

Retain total/idempotent lifecycle recovery, real checkpoint consumer, independent prior activity/pause, bounded systemd/backend effects, independent reporting and non-replayed unknown delivery. Additional hostile-spool/cross-UID/crash-matrix cases go to D1/D2 unless evidence shows a present MVP invariant failure.

The three operating principles remain Coin availability, no OOM and seamless dynamic-context handovers. Keep correct obligations, evidence and narrow sound mechanisms; delete false decompositions at the owning implementation task. Deferred hardening has one queue in the new index. No services, runtime state, credentials or code were changed by this planning replacement.
