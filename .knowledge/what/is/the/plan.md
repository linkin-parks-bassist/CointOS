---
status: green
revised_at: "2026-09-26T10:52:29+10:00"
---

Build the architecture in `what/is/the/architecture/of/cointos.md` in milestones. Each milestone ends with a live demonstration on the real machine and a green `cointos check`.

1. **Config and models.** `config/cointos.json` and a start routine that loads both models in their configured shapes through Lemonade and confirms the effective launch. *Live:* both models loaded with the configured context and lanes; memory figures in the ledger.
2. **Daemon, ledger and gateway.** `cointosd` with the ledger, the loopback API, the gateway and the scheduler (per-request lanes, priority classes, Coin's reserved lane, output cap), plus `cointos status` and `cointos check`. *Live:* three concurrent streaming requests on the work model share its two lanes, and a Coin-priority request is served next.
3. **Agents.** OpenCode agents launched through the gateway in per-agent git worktrees (`how/to/launch/opencode/for/a/cointos/agent.md`), with stopped runs resumed. Add `cointos agents`, `jobs`, `stop` and `go`. *Live:* four agents with small real tasks share two lanes and finish; killing one mid-run resumes its task.
4. **Autonomy.** The spawner, knowledge-tree queues, roles, and workers merging their branches when done. *Live:* one unattended hour in which queue items advance to done with commits.
5. **Coin.** The Telegram service using the daemon API, the gateway (reserved lane) and kt MCP tools, with a bounded number of tool rounds per turn. Add `cointos halt` and `up`. *Live:* the Coin-under-load scenario from the spec.
6. **Guard and dashboard.** Physical limits from the config, and the dashboard on the ledger. *Live:* the full acceptance in `what/is/the/spec.md`.
7. **Sole Survivor** (after the MVP): an agent started in guard emergencies to diagnose and repair them.

The core stays around 3,000 lines (`how/to/keep/cointos/simple.md`).
