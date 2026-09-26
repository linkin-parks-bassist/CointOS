---
status: green
revised_at: "2026-09-26T10:51:52+10:00"
---

Requirements for the CointOS MVP. The vision is `what/is/cointos.md`; the design is `what/is/the/architecture/of/cointos.md`; the working rules are `how/to/keep/cointos/simple.md`.

## Requirements

1. **Coin always answers.** A Telegram message gets a visible reply within 15 s whenever the machine is up. Coin can report status, list agents, queue work, draft ideas into knowledge trees, and stop, halt and restart the system.
2. **The workstation stays usable.** The desktop stays responsive while agents run. David's own local agent sessions outrank background agents.
3. **The GPU stays busy.** With work available, both work-model lanes are in use most of the time, shared among more live agents than lanes.
4. **Work moves without David.** Agents pick up urgent and queued items, break down drafted ideas, survey configured projects and do maintenance. Item leaves show their status, and results land as commits in the project repositories.
5. **Agent work continues.** A task (a queue item or a request from David) persists until it is done or blocked. If the agent working on it stops for any reason, the task is resumed by a new run, continuing the same OpenCode session where it exists.
6. **The system notices problems.** A stopped or stuck agent, an idle lane with work waiting, or a looping agent is detected and handled within a minute, and shown to David.
7. **One control surface.** `cointos status|agents|jobs|check|stop|go|halt|up` and the dashboard at `http://127.0.0.1:4200` show and control everything, from the ledger.

## Acceptance (seen live)

- **Soak:** 2 hours unattended with at least 4 live agents on the 2 work lanes. `cointos check` stays green throughout, and at least 3 queue items reach `Status: done` with commits.
- **Coin under load:** 10 Telegram messages spread across the soak all get visible replies within 15 s.
- **Workstation:** David uses the desktop normally during the soak without sluggishness. His own local OpenCode session is served ahead of background agents.
- **Halt/up:** `cointos halt` mid-soak leaves no CointOS process running and no model loaded. After `cointos up`, the interrupted tasks resume.
- **Kill test:** killing an agent process mid-run is detected and its task resumed within 30 s, with `cointos check` green again afterwards.

## Later

KV-cache snapshots; changing lane shapes at runtime; several work models at once; Sole Survivor as an agent; deeper review hierarchies.
