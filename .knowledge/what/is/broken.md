---
status: green
revised_at: "2026-10-01T22:19:10+10:00"
---

The unresolved defects and unproved boundaries are:

- **Automatic managerial recovery lacks live proof.** Failed worker items now route through one bounded manager pass using lifecycle state and assignment/receipt evidence, without magic report phrases. Unit coverage checks confirmed blockers, exhausted retries, brief correction, invalid prerequisite readiness and unresolved-manager escalation. Live automatic handoff and manager completion remain unproved; a manually queued Pigen correction does not establish this boundary.
- **Oversized read-heavy work can consume every fresh retry without an artifact.** Bounded recovery and manager supersession now fail honestly, but useful completion after an artifact-preserving fresh recovery remains unproved.
- **Warm reboot recovery after the second-pass repairs is unproved.** Complete normalized system/developer-prefix pinning and active-unit-only run adoption are installed and unit-covered. A later explicitly authorized reboot must prove warm disk-tier reuse and that dead units return tasks to waiting without charging an attempt.
- **OpenCode 1.18.33 has no verified message-free noninteractive session continuation.** Empty `run --session` exits with “You must provide a message or a command.” CointOS therefore sends the real user turn `Continue.` for gaps under three hours and one concise reorientation after longer gaps. Zero-message continuation would require another verified OpenCode interface; it does not block current work.
- **Several receipt/recovery paths lack focused live proof:** stale-run refusal against a newer active run, ordinary process-death auto-resume, loop handling, remaining budget-exhaustion cases and halt/up. CLI-launched system-operator completion and proactive sequential same-role prefix reuse are proved.
- **Full acceptance is incomplete:** Coin visible-reply latency under load, workstation responsiveness and user priority, multi-agent integration/send-back, two-lane/four-agent sustained soak, and ordinary-intake pipeline quality still need live evidence.
- **Snapshot durability needs churn evidence:** disk restores, save-size estimation, owner retirement, the reported `app.slice` OOM victim and a guarded midnight crossing remain unresolved.
- **Manager parallelism and local-agent output quality need observation**, but CointOS development must not wait on slow Pigen output for primary evidence.
- **Automatic retirement is installed; remaining retained work needs observation.** `lifecycle.retire` now retires settled done/failed/superseded/returned tasks in bounded reconciliation batches, archives unlanded commits and keeps dirty or still-revisable work for inspection. Its pure mechanism is covered by tests; retained failed items may be legitimate recovery artifacts rather than leaks.
- **The installed steward stalled-frontier rule still needs live confirmation.** New steward assignments now treat an approved but unqueued project frontier as a loose end owed one manager command; knowledge edits do not consume that allowance. A new scout must demonstrate this for Pigen's Task 6. An existing resumed OpenCode conversation can retain the earlier prompt.
- **Interactive sessions are invisible to agents.** A Claude Code session David runs in a project does not appear in `cointos agents`, and there is no channel to message a running agent. On 2026-10-01 the steward (system:loose-ends-8) spent its pass investigating that session's edits as an unknown concurrent writer, and an explanatory commit body did not reach it (it read commits with `--format='%s'`, subjects only). An unapproved remedy: a presence record for interactive sessions, registered through Claude Code hooks.
- **OpenCode V2 migration is deferred.** The installed runtime is 1.18.33; V1 remains authoritative until an isolated compatibility exercise proves process ownership, permissions, MCP, event parsing, retries and session resume.

`what/is/the/live/acceptance/evidence/for/cointos.md` owns the proven boundary. `what/is/the/plan.md` owns only the ordered remaining work.
