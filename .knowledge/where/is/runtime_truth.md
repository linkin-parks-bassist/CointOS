---
verified_at: '2026-09-11T15:40:39+10:00'
verified_by: codex /root
scope: project local
source: docs/system-map.md; docs/status.md; docs/operations.md; checked state/log directory layout 2026-09-11
verification: Compared documented truth boundaries with existing state, log, configuration, and service paths.
review_when: Recheck after persisted-state layout, service names, or backend endpoints change.
---

Live truth is not in `docs/status.md` or old agent notes. Establish it from the
smallest applicable combination of current `state/` records, append-only
`logs/runs/*.jsonl`, `systemctl --user`, current process identity, and fresh
Lemonade/backend observations. Configuration under `config/` expresses policy or
desired values, not proof that a service loaded them. A process exit of zero is not
semantic completion; inspect the durable outcome and required artifacts.

Use `docs/operations.md` for the relevant observation command, then query only the
named service/state owner. Never rewrite JSONL while summarizing or reconciling.
