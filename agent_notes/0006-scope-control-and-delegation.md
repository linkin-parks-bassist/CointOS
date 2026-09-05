# Scope control and delegation

Status: binding design note; mechanical enforcement pending.

At 09:04 AEST on 2026-09-04, Nameless Dave (Steward agent) began what David intended
as a fast, coarse restart-or-abandon view over old and queued work. The assigned
prompt instead demanded a per-job forensic inventory. Nameless Dave inspected about
30 job records, lifecycle logs, verification state, notes, and the `pigen` worktree.
The run lasted 20 minutes, produced more than 80 KiB of transcript, and saturated
the Qwen inference slot. It exited naturally immediately before an attempted
operator interrupt and entered verification, but its log ends during investigation
without the requested scan-friendly verdict. The work was relevant; its granularity
and stopping behavior were wrong. The Steward role advertised a ten-minute default,
while the executor enforced only its global 30-minute ceiling.

Rules and lessons:

- Task intake must state the decision altitude as well as the subject.
- Decompose broad collection scans into deterministic inventory/extraction, small
  bounded judgment batches, and one coordinator synthesis.
- For a coarse decision, group by outcome or domain and sample enough evidence;
  do not individually reconstruct every item.
- Each child task needs a maximum item count, wall time, output size, explicit
  deliverable, acceptance criteria, and stop condition.
- Deliver a useful partial answer before optional deeper inspection.
- Treat adjacent repository investigation as a separate child task or handoff.
- Enforce role/task budgets mechanically and add a live wrap-up/cancel channel.
- Delegation improves boundedness before true parallel execution exists, but must
  not generate unbounded queues, recursive handoffs, or ceremonial microtasks.

Recorded by Palinode (Codex agent), 2026-09-04.
