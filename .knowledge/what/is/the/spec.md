---
status: green
revised_at: "2026-09-27T14:25:27+10:00"
---

Requirements for the CointOS MVP. The vision is `what/is/cointos.md`; the design is `what/is/the/architecture/of/cointos.md`; the working rules are `how/to/keep/cointos/simple.md`.

## Requirements

1. **Coin always answers.** A Telegram message gets a visible reply within 15 s whenever the machine is up. Coin can report status, list agents, queue work, draft ideas into knowledge trees, and stop, halt and restart the system.
2. **The workstation stays usable.** The desktop stays responsive while agents run. David's own local agent sessions outrank background agents.
3. **The GPU stays busy.** With work available, both work-model lanes are in use most of the time, shared among more live agents than lanes.
4. **Work moves without David.** Agents pick up urgent and queued items, break down drafted ideas, survey configured projects and do maintenance. Item leaves show their status, and results land as commits in the project repositories.
5. **Agent work continues.** A task (a queue item or a request from David) persists until it is done or blocked. If the agent working on it stops for any reason, the task is resumed by a new run, continuing the same OpenCode session where it exists.
6. **The system notices problems.** A stopped or stuck agent, an idle lane with work waiting, or a looping agent is detected and handled within a minute, and shown to David.
7. **The scheduler is pre-emptive.** David has intended this since inception. A lane can be taken from the agent using it at any moment, mid-generation, and given to another; the interrupted agent resumes later where it stopped, losing no work. Nothing an agent does holds a lane beyond the scheduler's decision. (David, 2026-09-26: "it has been the intention since inception that the cointos scheduler would be pre-emptive.")
8. **One control surface.** `cointos status|agents|jobs|check|stop|go|halt|up` and the dashboard at `http://127.0.0.1:4200` show and control everything, from the ledger.

9. **Pipelined work at every level.** Every assignment is one bounded stage that consumes a bounded input and leaves a checkable artifact, an explicit boundary and the next handoff. This applies to decomposition, implementation, verification, integration, maintenance and recomposition. Manager runs advance one decomposition layer and may hand off another decomposition frontier. New software proceeds through small skeleton tasks, a focused test-contract task before each matching function implementation, then bounded integration layers that assemble already-tested parts into the complete system. Workers complete one such stage; integrators verify and land one boundary; higher-level review operates over a bounded set of contracts. Routine gardeners verify 1–3 leaves, while separate auditors inspect one structural concern. Agents calculate with code/tools. See `what/is/the/shape/of/cointos/work.md`.

## Acceptance (seen live)

- **Soak:** 2 hours unattended with at least 4 live agents on the 2 work lanes. `cointos check` stays green throughout, and at least 3 queue items land with commits (in the integrator workflow, their leaves are removed and Landed: trailers identify them).
- **Coin under load:** 10 Telegram messages spread across the soak all get visible replies within 15 s.
- **Workstation:** David uses the desktop normally during the soak without sluggishness. His own local OpenCode session is served ahead of background agents.
- **Halt/up:** `cointos halt` mid-soak leaves no CointOS process running and no model loaded. After `cointos up`, the interrupted tasks resume.
- **Kill test:** killing an agent process mid-run is detected and its task resumed within 30 s, with `cointos check` green again afterwards.

## Implementation status

The requirements above remain the acceptance contract. Snapshot-based pre-emption and disk snapshot tiers are already implemented. The event-silence threshold is now 30 seconds, shared by the recovery loop and self-check and including stalled startup; a suspended-startup live test recovered in 29.97 seconds with sampled self-checks green. This verifies that failure scenario, not every failure or the full acceptance suite. Current evidence and other gaps belong to `what/is/the/state.md`; completed ledger tasks are not a substitute for the acceptance scenarios.

## Recovery boundary

Automatic recovery is bounded and mechanical: preserve tasks, stop distressed work, unload/reload models and restart services as configured. Catastrophic diagnosis and repair are for David and a stronger remote agent. An autonomous Sole Survivor agent is off the current roadmap, subject to David revisiting the decision.

## Later

Changing lane shapes at runtime; several work models at once; deeper review hierarchies.
