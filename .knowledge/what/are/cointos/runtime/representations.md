---
status: green
revised_at: "2026-10-14T23:11:11+11:00"
---

- **Task:** durable assignment state: identity, generated personal name, place, kind/role, branch/worktree, queue relation and the record version it was made for, dependencies, budget, reasoning effort, status, current run, session, receipt and retry/recovery metadata.
- **Retirement:** after settlement and run exit, `lifecycle.retire` removes the checkout and handles its branch: delete when main contains it, archive dead branches under `refs/cointos/archive/` preserving commits, or retain blocked revisable branches (`git.add_worktree` recreates their checkout). Uncommitted checkouts and projects no longer configured remain for inspection. Integrator release retires its accepted worker immediately; each `reconcile` pass retires up to `recovery.retire_per_tick` other settled tasks. The task records `retired`.
- **Run/agent:** one transient attempt to execute a task, represented by a systemd unit, OpenCode server/client, gateway identity and observed activity. Runs never own task outcome.
- **Conversation:** OpenCode's durable session messages. It survives ordinary run replacement.
- **Thought:** one model reply from rendered conversation to answer/tool calls. It may be suspended between bounded GPU steps.
- **Lane:** one loaded-model execution slot holding at most one known token state.
- **Snapshot:** a disposable cache of a known token prefix, in RAM or on disk. It is never the conversation record.
- **Receipt:** the sole semantic statement that a bounded assignment completed, blocked or returned, and a worker's whole account of its work. The lifecycle reducer validates and records it.
- **Queue record:** desired project work: what is asked (brief, dependencies, stage, effort, budget), its order, holds, a `version` counting revisions, and one terminal fact written once by the lifecycle, `done` (or `replaced_by` when replaced). Where it stands otherwise (queued, blocked, awaiting its manager, and the blocker text) is never stored: `queues.state` derives it from the tasks made for its current version, and `queues.view` serves records with it.

Sessions, units, snapshots and ancestry cannot replace process, task, conversation or acceptance authority.
