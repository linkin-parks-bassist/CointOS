---
status: "green"
revised_at: "2026-09-26T09:24:46+10:00"
---

Roles are organised in three classes (David). The starting set is deliberately minimal and "vaguely the right shape"; David will refine the role files, and roles diversify within each class as practice shows the need.

- **Steward class:** keeps the system itself alive and healthy.
  - **Sole Survivor** (`roles/sole_survivor.md`): emergency custodian during a resource incident. It writes its conclusion first, then contains, repairs and recovers.
  - **Cointelprofessional, "Coin"** (`roles/_control-plane.md`): the always-available Telegram remote control and contact surface.
  - **Steward** (`roles/steward.md`): routine maintenance checks, drawn from the `steward-tasks/` card deck.
- **Managerial class** (`roles/manager.md`): keeps each project's work queue full of the right things in the right order. It breaks drafted ideas into queued items, surveys projects to queue next steps, and reviews finished work. It decides *what*.
- **Worker class** (`roles/worker.md`): carries out one queued item (implement, check, commit) and updates the item leaf. It decides *how*.

`roles/_base.md` is shared by every spawned agent. It covers orientation through knowledge trees, doing one step well, evidence over claims, committing in the workspace, and the queue conventions. `ecosystem/roles.py::build_prompt` composes an agent's prompt as base, then role file, then the assignment. The executor runs OpenCode in the job's contracted workspace, so project work happens in that project's repository.

**Queues live in project knowledge trees** (layout still experimental). For each project under `~/Projects/<repo>/.knowledge/`:

- `what/is/urgent/<item>.md` and `what/is/queued/<item>.md`: work items for workers;
- `what/is/drafted/<item>.md`: ideas David drafted, for managers to break down.

An item leaf's first line is its status (`Status: queued`, `in progress`, `blocked`, `done`, or `drafted` for ideas). The rest is the item's current brief, never a progress log. The installed CointOS tree (`~/.CointOS/.knowledge`) holds the cross-project view. How the spawner picks work is in `how/does/the/cointos/spawner/choose/work.md`.

**Coin edits knowledge trees directly, through the knowledge-tree MCP server.** Coin is not an OpenCode session, so it has no MCP host of its own. `ecosystem/knowledge_tools.py` is a minimal stdio MCP client. For each deep control turn, `ecosystem/control_worker.py` starts `~/.knowledge/.tools/kt-mcp` with the installed CointOS tree as its local root. The 23 `kt_*` tools are appended to Coin's own tools in `ecosystem/control_agent.py`, and each call is audited as `control.kt_tool`. If the server cannot start, Coin continues without the tools. The control-worker unit can write to `~/.knowledge`, `~/Projects` and `~/.local/state/knowledgetrees`. Client access elicitation is not supported, so an access request returns a pending ID that Coin confirms with David in conversation.

Sole Survivor's identity is hard-wired in the scheduler, proxy and workload control (`authority_profile` and `role` both `sole_survivor`); keep that name. Independent verification jobs (`ecosystem/verification.py`) run as `manager`. Role priorities within the default band are in `config/scheduling.json` (`worker` 550, `manager` 450, `steward` 400). Keep deterministic watchdog liveness checks and trusted scheduling provenance as system mechanisms, separate from roles.
