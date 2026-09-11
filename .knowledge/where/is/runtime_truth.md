---
verified_at: '2026-09-11T16:08:00+10:00'
verified_by: codex /root
scope: project local
source: live service and filesystem checks 2026-09-11; git show fe92546:docs/status.md; git show fe92546:docs/decisions/0021-runtime-state-home.md
verification: Verified the physical trees remain under ~/.CointOS, the former repo compatibility links are absent, and affected user services are stopped pending an explicit runtime-root refactor.
review_when: Recheck after persisted-state layout, service names, or backend endpoints change.
---

Live truth is not in historical plans, reports, or commits. Its physical home is
`/home/david/.CointOS`: live records are under `~/.CointOS/state` and append-only
run evidence is under `~/.CointOS/logs`. There are intentionally no repository
compatibility paths. Code that still assumes repo-relative `state/` or `logs/` is
not safe to run and the affected services remain stopped until that assumption is
refactored. Establish truth from the smallest applicable combination of current
state records, append-only run JSONL,
`systemctl --user`, current process identity, and fresh
Lemonade/backend observations. Configuration under `config/` expresses policy or
desired values, not proof that a service loaded them. A process exit of zero is not
semantic completion; inspect the durable outcome and required artifacts.

Use `how/to/operate/cointos.md` for the relevant observation boundary, then query
only the named service/state owner. Never rewrite JSONL while summarizing or
reconciling.
