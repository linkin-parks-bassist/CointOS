---
status: green
revised_at: "2026-10-05T12:49:37+11:00"
---

How CointOS is built and changed:

1. **One number, one place.** Every default limit, threshold, lane count, context size, priority and interval lives once, in `config/cointos.json`. Code derives everything else from it. Explicit task-budget overrides live in daemon-owned task metadata; configuration owns their defaults.
2. **One writer per fact.** The daemon alone writes the ledger (`state/cointos.json`); everything else reads it through the daemon's local API.
3. **Act on physics.** Work is admitted whenever there is a free lane. Physical resource pressure governs resource shedding. Separately, measured generation time/tokens bound an agent run under its configured work budget; waiting, prefill and tools do not spend it.
4. **Recovery is simple.** When an agent run dies or stalls, it is killed, logged, and its task goes back in the queue to be resumed. Ordinary interruption retains its session. Exhausting a run's generation budget permits only the configured number of fresh-session retries with artifacts preserved (none for worker items); failed worker items receive one bounded manager pass with their assignment, receipt evidence and last recovery packet. An unresolved or exhausted manager escalates for intervention. Recovery preserves bounded verified leads from outward text, tool results and Git state, never hidden reasoning. The run budget is the only per-run limit: the work model typically spends long silent stretches before writing, so no earlier progress checkpoint stops a run.
5. **Done means working live.** A change is done when `cointos check` stays green through its scenario on the real machine. Unit tests cover pure functions.
6. **Changes go to the owning concept.** A fix belongs where the concept it concerns is defined. Deleting code is as good a fix as adding it.
7. **No patches.** Every bug fix starts by asking what in the current design allowed the bug: two sources of truth, a missing bound, a proxy measured instead of the real thing, a concept without an owner. The fix changes that design, and the architecture leaf with it. A new state, flag, special case or retry that only covers a symptom is not a fix. (User requirement: "No patches... This will not become a swamp again.")
8. **Small core.** Daemon, gateway, scheduler, spawner, guard and self-check together stay around 3,000 lines or fewer.
9. **Functions over data.** Plain data and plain functions (`global:how/to/approach/architecture-design.md`).
10. **Leaves state current truth.** Each fact lives in its owning leaf and is updated in place. Code and leaves agree.
11. **Report plainly.** Say what was done and what was seen live.
12. **No unrequested limits.** Limits exist to stop a confused, scope-creeping agent from spending hours on nothing of value. A new limit, checkpoint or kill condition on agent work needs the user's explicit approval and evidence that it catches that failure without stopping normal runs.
