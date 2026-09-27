---
status: green
revised_at: "2026-09-27T17:00:00+10:00"
---

Requirements for the CointOS MVP. The vision is `what/is/cointos.md`, the design is `what/is/the/architecture/of/cointos.md`, and the working rules are `how/to/keep/cointos/simple.md`.

## Requirements

1. **Coin always answers.** A Telegram message gets a visible reply within 15 s whenever the machine is up. Coin can report status, list agents, queue work, submit general commands, and stop, halt and restart the system.
2. **The workstation stays usable.** The desktop stays responsive while agents run. David's own local agent sessions outrank background agents.
3. **The GPU stays busy.** With work available, both work-model lanes are in use most of the time, shared among more live agents than lanes.
4. **Work moves without David.** Agents pick up urgent and queued items, carry out general commands, survey configured projects and do maintenance. Runtime queues show scheduling status, and results land as commits in the project repositories.
5. **Agent work continues.** A task (a queue item or a request from David) persists until it is done or blocked. If the agent working on it stops for any reason, a new run resumes the task, continuing the same OpenCode session where it exists.
6. **The system notices problems.** A stopped or stuck agent, an idle lane with work waiting, or a looping agent is detected and handled within a minute, and shown to David.
7. **The scheduler is pre-emptive.** David has intended this since inception. A lane can be taken from the agent using it at any moment, mid-generation, and given to another; the interrupted agent resumes later where it stopped, losing no work. Nothing an agent does holds a lane beyond the scheduler's decision. (David, 2026-09-26: "it has been the intention since inception that the cointos scheduler would be pre-emptive.")
8. **One control surface.** `cointos status|agents|jobs|check|stop|go|halt|up` and the dashboard at `http://127.0.0.1:4200` show and control everything, from the ledger.
9. **Pipelined work at every level.** Every assignment is one bounded stage. It consumes a bounded input and leaves a checkable artifact, an explicit boundary and the next handoff. The rule covers decomposition, implementation, verification, integration, maintenance and recomposition. New software is built from small skeletons, then a focused test contract before each function, then bounded integration layers. Agents calculate with code and tools. `what/is/the/shape/of/cointos/work.md` owns the details and the current sizing calibration.

## Acceptance (seen live)

- **Soak:** 2 hours unattended with at least 4 live agents on the 2 work lanes. `cointos check` stays green throughout, and at least 3 queue items land with commits. Integrators explicitly signal the daemon after merging; it settles the records and their dependencies.
- **Coin under load:** 10 Telegram messages spread across the soak all get visible replies within 15 s.
- **Workstation:** David uses the desktop normally during the soak without sluggishness. His own local OpenCode session is served ahead of background agents.
- **Halt/up:** `cointos halt` mid-soak leaves no CointOS process running and no model loaded. After `cointos up`, the interrupted tasks resume.
- **Kill test:** killing an agent process mid-run is detected and its task resumed within 30 s, with `cointos check` green again afterwards.
- **Pipeline:** a request that enters through ordinary intake is decomposed, implemented, integrated and recomposed in bounded stages, with no manual decomposition, and the result meets its own acceptance.

`what/is/the/plan.md` lists the remaining acceptance work. Completed ledger tasks do not substitute for the scenarios.

## Recovery boundary

Automatic recovery is bounded and mechanical. It preserves tasks, stops distressed work, unloads and reloads models, and restarts services as configured. Catastrophic diagnosis and repair are for David and a stronger remote agent. An autonomous Sole Survivor agent is off the current roadmap unless David revisits the decision.

## Later

Changing lane shapes at runtime; several work models at once; deeper review hierarchies.
