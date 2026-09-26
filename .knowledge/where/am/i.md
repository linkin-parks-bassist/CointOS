---
status: "green"
revised_at: "2026-09-27T00:26:51+10:00"
---

CointOS is David's autonomous, local-first agent ecosystem. This checkout on `rebuild/simple-core` is both its source and its installed runtime: the enabled `cointosd.service` and `cointos-coin.service` run here, and `~/.local/bin/cointos` points to `bin/cointos`.

The Python implementation is in `cointos/`, configuration in `config/cointos.json`, agent prompts in `roles/`, dashboard in `web/`, unit templates in `systemd/`, and pure-function tests in `tests/`. Runtime state is under `state/`. The pre-emptive core is implemented and agents have completed work; full acceptance remains to be demonstrated. Only the sandbox is configured for autonomous project work.

Read these first, in order:
1. `what/is/cointos.md`: purpose and priorities.
2. `how/to/keep/cointos/simple.md`: governing development rules.
3. `what/is/the/architecture/of/cointos.md`: design and implementation boundaries.
4. `what/is/the/spec.md`, `what/is/the/plan.md`, `what/is/the/state.md`, `what/is/next.md`: requirements, milestones, evidence and next work.

Tree branches:
- `what/` owns purpose, architecture, project lifecycle, roles, machine and model facts.
- `how/` owns development rules and Lemonade, Telegram and OpenCode procedures; for example `how/to/launch/opencode/for/a/cointos/agent.md`.
- `where/` owns this orientation and the archive reuse map at `where/are/reusable/cointos/parts.md`.
- `why/`, `does/` and `is/` are currently empty.

The previous installation at `~/.CointOS` is retained but its old `agent-*` services are inactive and activatable units disabled. The current `cointos halt` stops this checkout's live system; it is not an old-installation cleanup prerequisite. Lemonade remains shared with other clients. Never touch `~/Avnet` or professional data.
