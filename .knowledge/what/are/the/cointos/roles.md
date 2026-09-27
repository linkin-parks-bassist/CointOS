---
status: green
revised_at: "2026-09-27T17:00:01+10:00"
---

Roles combine roles/_base.md, their role file and a bounded assignment from agents.prompt. Every level follows the pipeline in what/is/the/shape/of/cointos/work.md: bounded input, one checkable artifact and interface, explicit next handoff.

- Stewards: Coin is the Telegram control service. The routine steward handles one health concern only if maintenance_project is configured. Gardeners verify at most garden.leaves_per_pass selected leaves, prioritizing non-green batches; tree auditors inspect one structural concern at their separate cadence. At most one gardener/auditor runs per tree.
- Managers perform one bounded decomposition or recomposition stage. They sketch skeletons, per-function test contracts, implementations and integration layers, elaborating only the next one to three concerns. They maintain the remaining planning frontier and propose tasks or general commands through the daemon API with cointos queue. They never write scheduler leaves. A decomposition manager queues children and uses cointos replace CHILD... to repoint dependencies, then commits and merges the plan and signals cointos finish. Command managers also signal finish after their stage.
- Workers implement one bounded stage, run checks and commit code plus .work-report.md on their branch. The report begins Status: done or Status: blocked and records evidence, interfaces, assumptions, ownership, errors and unresolved mismatches. Oversized tasks include Needs decomposition:. Workers propose knowledge corrections in the report and never land their own changes.
- Integrators review one worker branch with cointos review. They accept or return it, maintain the project's own knowledge tree, plan and broken leaves, and commit and merge through cointos land. This preserves the report in the commit message, removes the temporary report file from main and signals the daemon to settle the task. cointos return sends substantial defects back with notes. There are no landing trailers or project queue endpoints.

Managers, gardeners and auditors land scoped changes with cointos merge. Gardening/auditing success requires normal stop, a clean worktree and merged branch; unresolved selected leaves remain explicit without requiring whole-tree repair. General commands replace drafted ideas; runtime scheduler records have the daemon as their only writer. Role classes remain distinct from GPU priority classes. The inactive Sole Survivor sketch is not scheduled.
