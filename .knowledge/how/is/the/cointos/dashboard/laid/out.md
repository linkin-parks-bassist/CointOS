---
status: green
revised_at: "2026-10-04T01:29:09+10:00"
---

The dashboard (`web/dashboard.html`, one self-contained page) leads its main column with the agent cards, then a **Pipeline** panel, then the Work lists; the side column holds Machine, Recently and Projects.

**Names.** Work items are shown as a headline plus context, not as raw slugs. `named(slug, project)` splits the slug at its first `task-<n>`: the words after it become the title-cased headline, while the project and the words up to `task <n>` become the context. Known acronyms such as RTL are upper-cased, `impl` and `param` are expanded, and `s<n>` becomes `§<n>`. For example, `elastic-rtl-task-5-test-contract-fix-s6-param-symbol` in pigen becomes "Test Contract Fix §6 Parameter Symbol" with the context "Pigen · Elastic RTL Task 5". Stages are title-cased, and kinds are named in words: Worker task, Integration review, Command, or the upkeep kind.

**Pipeline.** Every work item (a queue record and/or its `item` task, keyed `project:item`; superseded ones skipped) sits in exactly one step, chosen in this order: Landed (queue record done, or a done task with no record), Integrating (a running `integrate` task names it as `worker`), Review (task `review`), Building (task `running`), Gave up (task failed with no live record), Blocked (unmet `Depends on` or queue status `blocked`), else Ready. Steps run Blocked → Ready → Building → Review → Integrating → Landed. The arrows march while the next step holds live work. Each step shows six chips plus a "+n more" chip. Gave-up items and running or waiting non-item tasks (garden, audits, steward, decompose, breakdown, operator) appear below as Gave up and Upkeep.

**Agent cards** are coloured by role: worker rose, integrator sage, manager amber, upkeep roles lilac. A filled role badge names the role, its verb, the project and the stage. Under the headline sits the context, and a five-stop track (Queued, Build, Review, Integrate, Landed) lights where the card's item is. An integrator's track follows the worker it reviews.

**Details.** Clicking a card, pipeline chip or Work row opens a right-hand drawer with everything the ledger holds for that task: step, statuses, stage, agent, budget, dependencies (✓ landed, ⏳ pending), integrations, branch, worktree, receipt, note, result, report, revision and full brief. The open task is kept in the URL hash, so `/#project:item` links straight to it. Escape or the scrim closes it.
