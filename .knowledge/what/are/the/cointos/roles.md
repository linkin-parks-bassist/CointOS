---
status: green
revised_at: "2026-09-27T11:59:47+10:00"
---

Roles form three classes. Spawned prompts combine roles/_base.md, the role file and a bounded assignment from agents.prompt. David owns their direction. The governing work shape is what/is/the/shape/of/cointos/work.md.

- **Stewards:** Coin (roles/_control-plane.md) is the separate Telegram control service. The routine steward (roles/steward.md) checks one health concern; it is scheduled only when maintenance_project is in projects, which sandbox-only scope excludes. The gardener (roles/gardener.md) verifies up to garden.leaves_per_pass selected leaves; routine samples are random, health repairs prioritize brown then yellow. The separate tree auditor (roles/tree-auditor.md) checks one structural concern across representative owners at garden.audit_every_seconds intervals. Gardening and auditing never run concurrently for the same tree.
- **Managers** (roles/manager.md) outline concern pipelines, elaborate only the next one to three items, and retain the remaining frontier in the parent idea. Surveys advance one frontier or compare neighboring boundary reports at a shared abstraction level. Managers own plan, next and queue; they do not implement features or recursively elaborate the whole project.
- **Workers** (roles/worker.md) implement one concern with a small explicit interface, checks and exclusions. Oversized assignments are blocked with a requested split. Workers compute with tools, publish the current interface contract in its owning leaf, and put their work account and boundary report in the item. They commit and stop; they never land or create their own follow-up queue.
- **Integrators** (roles/integrator.md, managerial class) review one worker's committed change and boundary report, run relevant checks and preserve the interface contract. They own project state and land one item as a squash commit through cointos review/land, or return it to the worker. Larger coherence questions go to bounded manager follow-up.

Managers, gardeners and auditors land their own scoped changes with cointos merge. A gardener succeeds when its branch has landed, its worktree is clean and its run ends normally. Selected leaves still non-green on main trigger an alert and remain explicitly unresolved; it need not repair every other leaf. An auditor has the same landing/clean/normal-exit conditions without a leaf repair batch. A no-change verification may succeed. These checks do not prove semantic quality.

Queues are project knowledge leaves under what/is/urgent, what/is/queued and what/is/drafted. Their first body line is Status: queued | in progress | blocked | done | drafted. Depends on: lists earlier item paths. A worker's done status awaits review; only a Landed: commit trailer satisfies downstream dependencies. The integrator removes a done item leaf; its account remains in git. A blocked item retains its leaf.

Review at higher abstraction levels currently uses manager surveys and interface leaves; a separately scheduled recursive review hierarchy is not implemented. roles/sole_survivor.md is an inactive sketch, not scheduled. Role classes are responsibilities, distinct from scheduler priority classes.
