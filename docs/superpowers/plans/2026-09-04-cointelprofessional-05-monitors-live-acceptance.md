# Monitors and live acceptance: MVP disposition

Reorganized by Astra (Codex `/root`), 2026-09-05, at David's request to strip the existing plans down and extend them into complete MVP bring-up.

**Status:** historical plan replaced by a proposed execution suite, pending David's approval. This page preserves the previous link and remaining obligations; it is not a second executable plan or a claim of live readiness.

**Start here:** [CointOS MVP index](2026-09-05-cointos-mvp-index.md) and [complete design](../specs/2026-09-05-cointos-mvp-design.md).

Move the first real contact proof forward to C5. Extend that same smoke driver with health, messaging, approved release and autonomous-cycle scenarios as each slice becomes ready.

**Current task owners:** C5; H4-H5; B4; P4; A5.

Retain actual Telegram/process/inference/resource evidence, no OOM increment, context handover and recovery postconditions. Stop local workers and observe process/request exit before every exclusive live test. Do not require a monitor fleet, exhaustive adversarial review or unrelated cleanup before first use; later bounded work is D1-D8.

The three operating principles remain Coin availability, no OOM and seamless dynamic-context handovers. Keep correct obligations, evidence and narrow sound mechanisms; delete false decompositions at the owning implementation task. Deferred hardening has one queue in the new index. No services, runtime state, credentials or code were changed by this planning replacement.
