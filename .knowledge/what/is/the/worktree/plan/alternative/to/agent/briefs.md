---
status: green
revised_at: "2026-11-21T01:06:04+11:00"
---

**Status: proposal only. Nothing is built, scheduled or committed to.** The user has not approved building it, and it is not on the plan.

**Idea.** Agents get no brief. Each worktree carries its own task knowledge, and every agent of a role starts from one identical prompt.

**Two plans.**
- *Project plan:* `what/is/the/plan` in the master checkout. The integrator controls it. Worktree agents read it but do not change it.
- *Task plan:* a bespoke tree inside one worktree, kept out of git. It holds the requirement, the current plan and notes. It exists only for that job.

**Lifecycle.**
1. A manager creates the worktree and writes its requirement and first task plan. It still adds the queue item, with dependencies and test bindings.
2. A worker spawns. The `knowledgetrees.info` hook says which worktree it is in; that is the only per-agent difference.
3. It reads the task plan and works, keeping the plan current.
4. If it dies, a new agent spawns in the same worktree and continues from the plan.
5. When the work is ready, only the work is committed. The bespoke tree stays out by being untracked.
6. The integrator lands the work and updates the project plan.

**Recovery.** A First Responder reads the worktree and either fixes the task plan, so the next agent carries on, or has a manager cut the job into new worktrees with smaller plans.

**Rules needed.**
- The agent can edit its plan but not its requirement or bound tests, or it could shrink its own job. The daemon protects the requirement and keeps test bindings.
- Plan upkeep is checked mechanically, for example a finish is refused while the plan is stale. Worker Tugazo committed nothing in about 90 minutes, so compliance cannot be assumed.

**What stays.** The queue, dependencies, test contracts, review, landing and role prompts. This replaces brief delivery, not planning, so a manager can still write a first plan that is too big.

**Would need changing.** Worktree creation, launch prompts, the kt root setup for an untracked tree, run admission, First Responder guidance and the manager's handoff. Live briefs and this scheme would have to coexist during any migration.

**Unproven.** The expected gains are continuation after a death without losing the thread, and less startup reading through a shared prompt prefix. Neither is measured. `knowledgetrees.info` must stay after the shared prefix or the cache gain is lost.

**Open questions.**
- How does the check judge that a plan is current rather than merely touched?
- Where does the protected requirement live so an agent can read but not write it?
- What happens to task plans after landing: deleted, or archived as evidence?
- Do reviewers and integrators read the task plan, or only the requirement and diff?

**If ever tried.** Implementers only, on a few real jobs, compared with the current median of 17,720 generated tokens per worker run.
