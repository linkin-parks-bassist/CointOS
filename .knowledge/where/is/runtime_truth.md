---
verified_at: '2026-09-11T16:03:00+10:00'
verified_by: codex /root
scope: project local
source: docs/system-map.md; docs/status.md; docs/operations.md; docs/decisions/0021-runtime-state-home.md; live service and filesystem checks 2026-09-11
verification: Verified repo compatibility links resolve to ~/.CointOS, the systemd path unit watches the physical jobs directory, and control services restarted successfully after migration.
review_when: Recheck after persisted-state layout, service names, or backend endpoints change.
---

Live truth is not in `docs/status.md` or old agent notes. Its physical home is
`/home/david/.CointOS`: live records are under `~/.CointOS/state` and append-only
run evidence is under `~/.CointOS/logs`. The repository's `state` and `logs` paths
are compatibility symlinks to those trees. Establish truth from the smallest
applicable combination of current state records, append-only run JSONL,
`systemctl --user`, current process identity, and fresh
Lemonade/backend observations. Configuration under `config/` expresses policy or
desired values, not proof that a service loaded them. A process exit of zero is not
semantic completion; inspect the durable outcome and required artifacts.

Use `docs/operations.md` for the relevant observation command, then query only the
named service/state owner. Never rewrite JSONL while summarizing or reconciling.
