---
scope: project local
status: "unverified"
source: "2026-09-17 coordinator reconciliation of Git, installed assets, live systemd units, focused checks, and owning KT leaves"
review_when: Update after material repository, installation, or live-service changes.
updated_at: "2026-09-17T13:41:36+10:00"
---

Development is on branch `docs/cointos-mvp-bringup`. Commit `493ed9c` containing backend-instance restart reconciliation and physical-capacity policy deduplication is pushed and installed. Explicit verification opt-in is installed and pending commit.

Inference acquisition covers fresh routing, unloaded-model realization, idle reclamation, priority-aware allocation, tool-boundary park/reacquire, ghost reconciliation, context rerouting, retained-session continuation, executor restart, and old-backend termination after Lemonade restart. The cancelled `ReservePolicyDeduplicator` is terminal and its allocations are released.

The machine's qualified GPU allocation capacity is 100 GiB. The 64 GiB sysfs value is informational. Physical reserve values exist only under `physical_capacity` and are merged into the validated inference scheduling view.

Ordinary successful tasks now complete directly. Independent verification runs only when intake records exact `verification_requested: true`, exposed by `ecosystem enqueue --verify`; the watchdog repairs only jobs already deliberately awaiting verification.

The current scheduler defect is repeated retained-session prefill consuming each fairness slice before useful progress. Focused verification for the latest slice: source compilation, 74 existing checks, and installed direct intake qualification of ordinary false versus explicit true. No new regression test was added.
