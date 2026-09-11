---
verified_at: '2026-09-11T16:50:00+10:00'
verified_by: codex /root
scope: project local
source: README.md; docs/status.md; docs/decisions/0021-runtime-state-home.md; existing project knowledge leaves; David amendments 2026-09-11
verification: Checked repository purpose, current branch, runtime relocation,
  service state, code/test entry points, and knowledge layout.
review_when: Recheck when project purpose, runtime layout, service activation,
  current priority, or primary development workflow changes.
---

This is `/home/david/agent-ecosystem`, David's personal, local-only CointOS
orchestration repository. It turns local/Telegram requests into durable agent work,
coordinates local inference and survival controls, and stores its implementation,
configuration, tests, plans, specifications, decisions, and agent-facing knowledge.
Do not mix professional, partner, or customer information into it.

Source lives primarily in `ecosystem/` and `survival/`; launch adapters are in
`scripts/` and `services/`; policy/configuration is in `config/`; standard-library
tests are in `tests/`; current project orientation continues through
`what/is/current/project_priority.md` and `where/is/code/for/cointos.md`.

Mutable runtime data is physically under `/home/david/.CointOS`, not this checkout.
There are intentionally no repo compatibility paths for `state/` or `logs/`.
Affected runtime services are stopped until the source/runtime-root split is
implemented. Establish live truth through `where/is/runtime_truth.md`; use
`how/to/test/cointos_changes.md` before claiming verification.
