---
scope: project local
status: "unverified"
source: "Git, installed assets, focused checks, and task-4894b791ecbcbafc runtime evidence 2026-09-17"
review_when: Update after material repository, installation, or live-service changes.
updated_at: "2026-09-17T15:00:33+10:00"
---

Development is on branch `docs/cointos-mvp-bringup`. Commits through `f0a2660` are pushed and installed. Proxy park/reacquire recovery and semantic OpenCode completion changes are installed and pending commit.

Inference acquisition covers fresh routing, unloaded realization, idle reclamation, priority allocation, tool-boundary park/reacquire, failed-park rollback, ghost reconciliation, context rerouting, retained-session continuation, executor restart, and old-backend termination after Lemonade restart. Ordinary successful tasks complete directly; independent verification requires exact opt-in.

The qualified GPU allocation capacity is 100 GiB. The 64 GiB sysfs value is informational. Physical reserves have one owner under `physical_capacity`. Production audit confirms 32 GiB protected host, 8 GiB coin/control, and 12 GiB load transient all stack in host admission; transient also enters GTT admission. Numeric necessity remains to be measured.

`ReserveArithmeticTracer` live-qualified multi-step park/reacquire and retained-session continuation across tool calls and scheduler rotations. It exposed two semantic completion holes: a zero client exit with no current `step_finish`, and post-stop OpenCode housekeeping surviving long enough for another rotation. No-finish exits now continue; explicit stop now terminates the attached client promptly. The preserved worker produced a complete report followed by `step_finish: stop`; the erroneous post-stop dispatch was discarded and durable completion recovered.

Equal-priority fairness begins at the first appended, session-matching `step_finish` event of the runner round, after retained-session prefill. Cancellation, allocation preemption, and higher-priority work remain immediate.

Latest evidence: source compilation, direct wrapper stream checks, 108 existing focused inference/executor checks, and the live multi-step managed worker. No new regression test was added.