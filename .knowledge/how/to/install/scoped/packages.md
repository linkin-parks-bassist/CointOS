---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local
source: scripts/install-package; services/privileged/agent-package-install; pre-99318d9 Git history
verification: Checked the repository entry points and recorded their authority boundary; no package installation run.
review_when: Recheck when the privileged wrapper or sudo policy changes.
---

Use `scripts/install-package NAME...` for explicitly authorized packages from
existing APT repositories. The root-owned wrapper permits named installations, not
arbitrary APT options, local packages, repository changes, removals, upgrades, or
general privileged commands. Inspect its records with
`journalctl -t agent-package-install`.
