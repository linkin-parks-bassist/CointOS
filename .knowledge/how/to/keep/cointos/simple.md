---
status: green
revised_at: "2026-10-15T23:47:49+11:00"
---

How CointOS is built and changed:

1. **One number, one place.** Every default limit, threshold, lane count, context size, priority and interval lives once in config/cointos.json. Explicit task-budget overrides live in daemon-owned metadata; configuration owns defaults.
2. **One writer per fact.** The daemon alone writes state/cointos.json; everything else reads its API.
3. **Act on physics.** Admit work when a lane is free. Physical pressure governs shedding. Measured generation time/tokens separately bound runs; waiting, prefill and tools do not spend generation budgets.
4. **Recovery preserves work and bounds roles.** Retain sessions, branches, files and outward evidence. recovery.role_fresh_retries overrides fresh_retries; workers, managers, integrators and Operators default to zero budget refills. Each canonical assignment/version has one capable recovery Operator with checked handback, deferred while valid children progress. Recovery does not create another manager-to-Operator chain. Role budgets come from recovery.role_budgets; task overrides win. Identical revisions cannot refill budgets. User holds stop related execution and recovery; a controller may continue only its own hold.
5. **Done means autonomous live behaviour.** Green checks and tests are necessary evidence, not proof that CointOS builds unattended. Acceptance requires agents to plan, validate, recover and progress without the supervising Codex writing product briefs or repairing product logic for them. Pigen is a test workload, not Codex's build objective. Direct intervention in managed projects is for undoing damage caused by CointOS defects; otherwise observe failures, reproduce them in CointOS fixtures, fix their system cause and verify unassisted continuation.
6. **Changes go to the owning concept.** Fix the concept where defined; deleting code can be the best fix.
7. **No patches.** Ask what design allowed the bug: duplicate truth, missing bound, proxy measurement or ownerless concept. Change that design and its architecture answer. A symptom-specific state, flag or retry is not a fix. User requirement: “No patches... This will not become a swamp again.”
8. **Small core.** Daemon, gateway, scheduler, spawner, guard and self-check together stay around 3,000 lines or fewer.
9. **Functions over data.** Plain data and functions; global:how/to/approach/architecture-design.md owns guidance.
10. **Leaves state current truth.** Each fact has one owner; code and answers agree.
11. **Report plainly.** Say what changed and what worked live, including remaining acceptance limits.
12. **No unrequested limits.** New limits, checkpoints or kill conditions need explicit user approval and evidence that they catch wasted work without stopping normal runs.
