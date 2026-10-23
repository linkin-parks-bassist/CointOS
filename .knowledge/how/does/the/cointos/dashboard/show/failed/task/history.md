---
status: green
revised_at: "2026-10-23T22:28:09+11:00"
---

The Work panel's **Failed** count button (beside **Done**) opens a list of every task with status failed except cancelled tasks. It includes superseded task versions, old integrator failures and earlier work whose queue record is now accepted or replaced. The count is failed task records, not unresolved product defects or individual model runs. The open list's explanatory text says old and superseded tasks remain visible and a failed manager's child work may still be running. Failures are preserved rather than hidden or marked accepted.

A manager can remain failed because its generation budget expired without a completion receipt while its successfully queued children continue running. Atomic manager handoff prevents the gap between dispatch and completion. Existing failed planning suppresses redundant recovery during healthy manager-owned handoffs; it does not falsely accept the manager. `how/does/cointos/recover/blocked/assignments.md` owns the policy and native evidence.

Read a task's drawer, current queue record, replacements, acceptance and active children before interpreting a historical failure as current obstruction. A missing live record alone cannot prove that the underlying issue was resolved. The drawer shows the current recovery owner and runnable continuation from work_frontier, while the count shows historical records. Genuine unresolved failures remain important. The project Pipeline no longer shows failed items (no gave-up group); this list is their only dashboard view. Source: `web/dashboard.html` renderWork and live ledger inspection.
