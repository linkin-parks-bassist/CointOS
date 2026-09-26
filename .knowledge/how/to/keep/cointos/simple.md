---
status: "green"
revised_at: "2026-09-26T14:07:58+10:00"
---

How CointOS is built and changed:

1. **One number, one place.** Every limit, threshold, lane count, context size, priority and interval lives once, in `config/cointos.json`. Code derives everything else from it.
2. **One writer per fact.** The daemon alone writes the ledger (`state/cointos.json`); everything else reads it through the daemon's local API.
3. **Act on physics.** Work is admitted whenever there is a free lane. Work is stopped only when a physical measurement of the machine crosses its configured limit.
4. **Recovery is simple.** When an agent run dies or stalls, it is killed, logged, and its task goes back in the queue to be resumed.
5. **Done means working live.** A change is done when `cointos check` stays green through its scenario on the real machine. Unit tests cover pure functions.
6. **Changes go to the owning concept.** A fix belongs where the concept it concerns is defined. Deleting code is as good a fix as adding it.
7. **No patches.** Every bug fix starts by asking what in the current design allowed the bug: two sources of truth, a missing bound, a proxy measured instead of the real thing, a concept without an owner. The fix changes that design, and the architecture leaf with it. A new state, flag, special case or retry that only covers a symptom is not a fix. (David: "No patches... This will not become a swamp again.")
8. **Small core.** Daemon, gateway, scheduler, spawner, guard and self-check together stay around 3,000 lines or fewer.
9. **Functions over data.** Plain data and plain functions (`global:how/to/approach/architecture-design.md`).
10. **Leaves state current truth.** Each fact lives in its owning leaf and is updated in place. Code and leaves agree.
11. **Report plainly.** Say what was done and what was seen live.
