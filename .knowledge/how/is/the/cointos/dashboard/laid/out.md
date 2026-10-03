---
status: green
revised_at: "2026-10-04T03:01:23+11:00"
---

The dashboard (`web/dashboard.html`, one self-contained page) has two views, chosen by the address hash: `#/` is home and `#/<project>` is a project page. `#/<project>/<task id>` additionally opens that task's detail drawer; home's form is `#//<task id>`. Both views lead with the agent cards (a project page shows only that project's agents), followed by the Work lists (filtered to the project on its page). On home, the side column holds Machine and Recently beside the main column. A project page gives the main column the full width and places those panels below.

**Home** shows one card per registered project, linking to its page. Each card has the project name, its open-item count, and the first line of its orientation answer. The daemon reads that line through `projects.about` and publishes it as the ledger's `project_about`. Below that are a segmented bar plus key counting the project's items at each pipeline step, then its running agents, or the last landing when none are running. Upkeep tasks whose place is not a registered project appear below the cards as System upkeep. The "Add or create project" form sits at the bottom of the panel; there is no separate project-settings panel.

**Project page** shows the project name, its orientation line and its registry settings: main branch, path, priority, enabled, and Remove (confirmed). Then comes its **Pipeline**. Each of the project's work items (a queue record and/or its `item` task, keyed `project:item`; superseded and cancelled ones skipped) sits in exactly one step, chosen in this order: Landed (queue record done, or a done task with no record), Integrating (a running `integrate` task names it as `worker`), Review (task `review`), Building (task `running`), Gave up (task failed with no live record), Blocked (unmet `Depends on` or queue status `blocked`), else Ready. Steps run Blocked → Ready → Building → Review → Integrating → Landed. The arrows march while the next step holds live work. Each step shows six chips plus a "+n more" chip. The project's gave-up items and upkeep tasks appear below.

**Names and summaries.** Items are shown as a headline plus context, not as raw slugs. `named(slug, project)` splits the slug at its first `task-<n>`: the words after it become the title-cased headline, while the project and the words up to `task <n>` become the context. Known acronyms such as RTL are upper-cased, `impl` and `param` are expanded, and `s<n>` becomes `§<n>`. For example, `elastic-rtl-task-5-test-contract-fix-s6-param-symbol` in pigen becomes "Test Contract Fix §6 Parameter Symbol" with the context "Pigen · Elastic RTL Task 5". The queue record's `summary` appears on chips, agent cards and as the drawer's lead. It comes from the brief's `Summary:` line, and an integration uses its worker's summary. Stages are title-cased, and kinds are named in words: Worker task, Integration review, Command, or the upkeep kind.

**Agent cards** are coloured by role: worker rose, integrator sage, manager amber, upkeep roles lilac. A filled role badge names the role, its verb, the project and the stage. The headline, context and summary follow, then a five-stop track (Queued, Build, Review, Integrate, Landed) that lights where the card's item is. An integrator's track follows the worker it reviews.

**Details.** Clicking a card, pipeline chip or Work row opens a right-hand drawer with everything the ledger holds for that task: step, statuses, stage, agent, budget, dependencies (✓ landed, ⏳ pending), integrations, branch, worktree, receipt, note, result, report, revision and full brief. Escape or the scrim closes it.

**Controls.** Buttons call the daemon's control API directly, and a toast reports each outcome or error.
- The header's **Pause all** / **Resume agents** calls `stop` / `go`; pausing asks for confirmation.
- Agent cards have **Pause**, which calls `kill-agent`: the run ends and its task is held until resumed. They also have **Cancel task**, which calls `cancel` after prompting for a reason.
- Busy GPU lanes have **free**, which pauses the lane's holder.
- Queue rows have **↑/↓**, which call `move`.
- The drawer's action bar offers whichever of these apply: Pause run, Resume (`resume-task`), Hold / Release hold (`hold`/`unhold`), Top / Up / Down / Bottom (`move`), Cancel task (`cancel`), and a Reasoning select (`reasoning`, effective from the next reply).
Every control is also a CLI command: `cointos stop|go|kill|resume|hold|move|cancel|reasoning`.
