---
status: green
revised_at: "2026-11-07T15:49:05+11:00"
---

How CointOS is built and changed:

1. **One number, one place.** Defaults, thresholds, lane counts, priorities and intervals live in config/cointos.json. Explicit task overrides live in daemon metadata.
2. **One writer per fact.** The daemon alone writes state/cointos.json; other components use its API.
3. **Act on physics.** Lane availability and physical pressure govern admission/shedding. Generation budgets exclude reading/waits/tools.
4. **Recovery preserves work and authority.** Retain sessions, branches, files and outward evidence. Configured fresh retries default to zero for construction/Operators. One recovery owner per assignment/version advances checked handoffs; valid children defer escalation. Identical revisions cannot refill budgets; user holds prevail.
5. **Change the system, not its inhabitants.** This is explicit policy for every agent developing or experimenting on the CointOS project. Observe live inhabitants read-only. Fix controller code, reusable instruction templates, configuration and system mechanisms; let autonomous operation expose their effects. Do not directly message/steer inhabitants or their supervisors, revise individual briefs, manually dispatch product/recovery help, alter their assignments/queues/holds, or implement managed product work to improve an outcome. Do not delegate those interventions to another development agent. General permission to fix/test CointOS is not permission to intervene. A specific user instruction is required for an exception, including undoing CointOS-caused damage. CointOS's own autonomous supervision/recovery remains part of the system under observation, not a developer workaround. Necessary authorised system deployment is recorded as an experimental boundary, not a clean uninterrupted run. Mark every manual intervention and affected runs in evidence; never count assisted results as natural autonomous acceptance. how/to/test/cointos.md owns experimental practice.
6. **Fix the owning concept.** Deleting code can be the best repair. A symptom-specific flag/retry is not a design fix; keep architecture and evidence aligned. User requirement: no patch swamp.
7. **Small core.** Daemon, gateway, scheduler, spawner, guard and self-check together stay around3,000 lines or fewer.
8. **Functions over data.** Follow the global architecture-design owner.
9. **Current knowledge.** Each fact has one owner; implementation and answers agree. Tests establish mechanisms, not unattended product progress. Pigen is an experimental workload, not the developer's compiler deliverable.
10. **Never claim CointOS is fixed.** This is an explicit user ground rule. Report the concrete change, observed behavior, observation period, interventions and remaining failures or uncertainty. Passing checks, installation, a temporary improvement or a single successful run do not justify “fixed,” “resolved” or equivalent completion claims. Sustained useful outcomes are evidence with a stated scope, never proof that the system is now fixed.
11. **No unrequested limits.** New budgets/checkpoints/kill conditions require explicit user authority and evidence that they catch waste without stopping normal work.
