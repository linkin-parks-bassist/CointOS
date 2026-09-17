---
scope: project local
status: "unverified"
source: "2026-09-17 coordinator reconciliation of Git, installed assets, focused checks, and owning KT leaves"
review_when: Update after material repository, installation, or live-service changes.
updated_at: "2026-09-17T13:44:41+10:00"
---

Development is on branch `docs/cointos-mvp-bringup`. Commits through `8ac275a` are pushed and installed. The prefill-aware fairness correction is installed and pending commit.

Inference acquisition covers fresh routing, unloaded realization, idle reclamation, priority allocation, tool-boundary park/reacquire, ghost reconciliation, context rerouting, retained-session continuation, executor restart, and old-backend termination after Lemonade restart. Ordinary successful tasks complete directly; independent verification requires exact opt-in.

The qualified GPU allocation capacity is 100 GiB. The 64 GiB sysfs value is informational. Physical reserves have one owner under `physical_capacity`.

Equal-priority fairness now begins at the first appended, session-matching `step_finish` event of the runner round, after retained-session prefill. Cancellation, allocation preemption, and higher-priority work remain immediate. This closes the observed repeated-prefill livelock by granting a full productive quantum without inventing a prefill duration.

Latest evidence: source compilation, 57 existing focused checks, and installed session-scoped step-boundary inspection. No new regression test was added.
