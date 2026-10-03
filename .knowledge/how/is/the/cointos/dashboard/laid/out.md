---
status: green
revised_at: "2026-10-04T01:17:23+10:00"
---

The dashboard (`web/dashboard.html`, one self-contained page) leads its main column with a **Pipeline** panel, then the agent cards, then the Work lists; the side column holds Machine, Recently and Projects.

**Pipeline.** Every work item (a queue record and/or its `item` task, keyed `project:item`; superseded ones skipped) sits in exactly one step, chosen in this order: Landed (queue record done, or a done task with no record), Integrating (a running `integrate` task names it as `worker`), Review (task `review`), Building (task `running`), Gave up (task failed with no live record), Blocked (unmet `Depends on` or queue status `blocked`), else Ready. Steps run Blocked → Ready → Building → Review → Integrating → Landed with arrows that march while the next step holds live work; each shows six chips plus a "+n more" chip. Gave-up items and running or waiting non-item tasks (garden, audits, steward, decompose, breakdown, operator) appear below as Gave up and Upkeep.

**Agent cards** are coloured by role (worker rose, integrator sage, manager amber, upkeep roles lilac). A filled role badge names the role, its verb, project and stage, and a five-stop track (Queued, Build, Review, Integrate, Landed) lights where the card's item is; an integrator's track follows the worker it reviews.

**Details.** Clicking a card, pipeline chip or Work row opens a right-hand drawer with everything the ledger holds for that task: step, statuses, stage, agent, budget, dependencies (✓ landed, ⏳ pending), integrations, branch, worktree, receipt, note, result, report, revision and full brief. The open task is kept in the URL hash, so `/#project:item` links straight to it; Escape or the scrim closes it.
