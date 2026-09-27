---
status: green
revised_at: "2026-09-27T14:13:35+10:00"
---

The pre-emptive core is implemented. The two-hour sandbox soak established check stability, four-agent concurrency and delivery; it did not establish Coin latency, workstation responsiveness or every recovery scenario. Small-concern role prompts, bounded gardening and a separate structural auditor are implemented but need live quality acceptance. Obsolete test work is erased; David has authorized a fresh C JSON-parser exercise through ordinary intake. what/is/the/state.md owns evidence, and what/is/next.md orders the remaining work. Sole Survivor is off the roadmap; catastrophic recovery remains David's remote intervention.

Build the architecture in `what/is/the/architecture/of/cointos.md` in milestones. Each milestone ends with a live demonstration on the real machine and a green `cointos check`.

1. **Config, models and backend.** `config/cointos.json`, and the backend layer launching both models through Lemonade in their configured shapes. *Live:* both models loaded with the configured context and lanes; memory and headroom in the ledger.
2. **Pre-emptive lanes.** `cointosd` with the ledger, the gateway, thoughts advanced in steps, switches with snapshots, and the scheduler (classes, reading holders, slices, tool-call yields with grace, reservations), plus `cointos status` and `cointos check`. *Live:* a Coin thought takes a busy lane within a few seconds and the pre-empted thought resumes warm; four agents share two lanes, each finishing its cold read before an equal pre-empts it.
3. **Agents.** OpenCode agents launched through the gateway in per-task git worktrees (`how/to/launch/opencode/for/a/cointos/agent.md`), with stopped runs resumed. Add `cointos agents`, `jobs`, `stop`, `go` and `watch`. *Live:* four agents with small real tasks share two lanes and finish; killing one mid-run resumes its task.
4. **Autonomy.** The spawner, knowledge-tree queues, roles, and workers handing committed changes to one integrator per project. *Live:* one unattended hour in which queue items advance to done with commits.
5. **Coin.** The Telegram service using the daemon API, the gateway (reserved lane) and kt MCP tools, with a bounded number of tool rounds per turn. `cointos halt` and `up` provide lifecycle control. *Live:* the Coin-under-load scenario from the spec.
6. **Memory and dashboard.** Headroom from both limits, snapshot tiers, distress, and the agents-first dashboard. *Live:* the full acceptance in `what/is/the/spec.md`.

The core stays around 3,000 lines (`how/to/keep/cointos/simple.md`).


**Current integration stage.** Validate the invariant that every level of work is internally pipelined: each manager run advances one decomposition boundary, each worker implements one concern, each integrator verifies and lands one boundary, and manager-level recomposition checks one shared contract layer. A stage may hand off another stage of the same kind; decomposition does not have to produce worker-ready items in one pass. After restoring ambient configuration, demonstrate a 1–3-leaf routine gardener and a separate single-concern tree audit. The old runs remain discarded; the fresh JSON-parser brief states only software requirements, with decomposition supplied by the infrastructure. Keep sandbox-only project scope. Keep OpenCode 1.18.32 unchanged by David's request. Its V2 assessment remains background knowledge for a future decision.
