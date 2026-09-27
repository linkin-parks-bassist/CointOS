---
status: green
revised_at: "2026-09-27T14:51:05+10:00"
---

CointOS is David's autonomous, local-first agent ecosystem. This checkout on `rebuild/simple-core` is both its source and its installed runtime: the enabled `cointosd.service` and `cointos-coin.service` run here, and `~/.local/bin/cointos` points to `bin/cointos`.

The Python implementation is in `cointos/`, configuration in `config/cointos.json`, agent prompts in `roles/`, dashboard in `web/`, unit templates in `systemd/`, and pure-function tests in `tests/`. Runtime state is under `state/`. The pre-emptive core is implemented and agents have completed work; full acceptance remains to be demonstrated. Only the sandbox is configured for autonomous project work. Obsolete test runs were erased; David has authorized a fresh C JSON-parser exercise through ordinary sandbox intake. Every role prompt now applies the same bounded pipeline rule at its own level, including decomposition and recomposition; bounded gardeners and a separate structural tree auditor are implemented, with live quality acceptance pending. OpenCode remains 1.18.32; V2 migration is deferred by David's request.

Read these first, in order:
1. `what/is/cointos.md`: purpose and priorities.
2. `how/to/keep/cointos/simple.md`: governing development rules.
3. `what/is/the/architecture/of/cointos.md`: design and implementation boundaries; `what/is/the/shape/of/cointos/work.md` and `what/are/the/cointos/roles.md`: bounded work and role ownership.
4. `what/is/the/spec.md`: requirements and acceptance; `what/is/the/plan.md`: the frontier (milestones, current state, evidence and ordered next work); `what/is/broken.md`: current defects.

Tree branches:
- `what/` owns purpose, architecture, project lifecycle, roles, machine and model facts.
- `how/` owns development rules and Lemonade, Telegram and OpenCode procedures; for example `how/to/launch/opencode/for/a/cointos/agent.md`.
- `where/` owns this orientation and the archive reuse map at `where/are/reusable/cointos/parts.md`.
- `why/`, `does/` and `is/` are currently empty.

The previous installation at `~/.CointOS` is retained but its old `agent-*` services are inactive and activatable units disabled. The current `cointos halt` stops this checkout's live system; it is not an old-installation cleanup prerequisite. Lemonade remains shared with other clients. `~/Avnet` and other professional data must never reach a hosted model other than the work-provided GitHub Copilot: a hosted assistant (Claude, Codex and the like) working on CointOS never reads it. CointOS's local agents run on local models, so the restriction is not about them.
