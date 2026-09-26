---
status: "green"
revised_at: "2026-09-27T00:27:35+10:00"
---

The core for milestones 1–6 is implemented, but their live acceptance is not all established. Both models match config; completed thoughts and restart adoption appear in the ledger. The four-agent completion/kill demonstration, Coin timing, uninterrupted hour and full soak still need evidence. Sole Survivor is not implemented. `what/is/the/state.md` owns the current evidence and gaps, and `what/is/next.md` orders the remaining work.

Build the architecture in `what/is/the/architecture/of/cointos.md` in milestones. Each milestone ends with a live demonstration on the real machine and a green `cointos check`.

1. **Config, models and backend.** `config/cointos.json`, and the backend layer launching both models through Lemonade in their configured shapes. *Live:* both models loaded with the configured context and lanes; memory and headroom in the ledger.
2. **Pre-emptive lanes.** `cointosd` with the ledger, the gateway, thoughts advanced in steps, switches with snapshots, and the scheduler (classes, reading holders, slices, tool-call yields with grace, reservations), plus `cointos status` and `cointos check`. *Live:* a Coin thought takes a busy lane within a few seconds and the pre-empted thought resumes warm; four agents share two lanes, each finishing its cold read before an equal pre-empts it.
3. **Agents.** OpenCode agents launched through the gateway in per-task git worktrees (`how/to/launch/opencode/for/a/cointos/agent.md`), with stopped runs resumed. Add `cointos agents`, `jobs`, `stop`, `go` and `watch`. *Live:* four agents with small real tasks share two lanes and finish; killing one mid-run resumes its task.
4. **Autonomy.** The spawner, knowledge-tree queues, roles, and workers merging their branches when done. *Live:* one unattended hour in which queue items advance to done with commits.
5. **Coin.** The Telegram service using the daemon API, the gateway (reserved lane) and kt MCP tools, with a bounded number of tool rounds per turn. Add `cointos halt` and `up`. *Live:* the Coin-under-load scenario from the spec.
6. **Memory and dashboard.** Headroom from both limits, snapshot tiers, distress, and the agents-first dashboard. *Live:* the full acceptance in `what/is/the/spec.md`.
7. **Sole Survivor** (after the MVP): an agent started in memory emergencies to diagnose and repair them.

The core stays around 3,000 lines (`how/to/keep/cointos/simple.md`).
