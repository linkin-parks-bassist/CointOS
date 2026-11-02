---
status: green
revised_at: "2026-11-03T05:28:37+11:00"
---

Current accidental capability gaps, from source and per-run agent logs. These are defects or friction, not user policy; they are separate from the deliberate guards in what/are/the/cointos/agent/capability/requirements.md.

- **kt writes:** branch-publishing confinement omits `~/.knowledge/.tools` and `~/.local/state/knowledgetrees`; `kt_add`/`kt_rewrite` fail with EACCES. The edit allowlist covers only the worktree, so knowledge edits resolving to canonical paths are also denied.
- **Publishing:** project Operators cannot publish product code, so a verified product fix must go through a queued worker and integrator.
- **Compaction:** OpenCode summary generation rejects tool calls, ending runs without receipts (`Tool call not allowed while generating summary`).
- **Read-only denials:** `dpkg -l|-s`, `systemctl` status/cat/show/is-active/list-units and `cointos ... --help` are allowed; other `systemctl` and `dpkg` commands stay denied without the operator control ability.
- **Installation/toolchain:** there is no `sudo`/`apt`/pip/npm-g capability; required tools such as verilator must be installed by the user. Landlock also omits ordinary caches (`~/.cache`, cargo/npm/pip caches) and canonical build checkouts.
- **MCP:** factory roles have no station tools, so they get only knowledgetrees and CointOS MCP; a stationed Operator gets what its station grants.
- **Landing granularity:** submission and landing compare whole registered commands. New commands and commands green on main must pass; only registered commands already red on pinned main qualify for exemption. A split implementation cannot claim assertion-level progress inside one covering command, and an already-red command can conceal changed failing assertions.
- **Recovery/retry:** workers, managers, integrators and operators have zero automatic fresh budget retries; infrastructure hiccups and some MCP finish timeouts become blocked work. Anti-loop guards should remain, but infrastructure retries should be distinguished from product refusals.

Every role has queue, hold, revise, cancel, supersede, budget, correct_tests, resume, check_work and dispatch, and web tools. api.controls_project refuses only a recovery whose origin was withdrawn or is held by someone else. The limits that remain on those tools: an implementer cannot correct its own acceptance tests, no agent raises its own budget, a First Responder calls no other First Responder, a stationed agent cannot widen what it starts, and Operators and First Responders cannot revise another owner's hold. Land, return, review and incorporate stay with integrators, for independent review.

Source owners: `opencode.py` settings/write_paths, `stations.py`, `mcp.py` TOOLS, `api.py` controls/queue, `contracts.maintenance_history`, `contracts.combined` and the landing gate, roles/_base and roles/integrator, plus live `state/events.jsonl` and per-run agent logs.
