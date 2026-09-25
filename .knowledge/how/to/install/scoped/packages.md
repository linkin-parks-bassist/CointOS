---
status: green
revised_at: "2026-09-20T08:44:30+10:00"
checked_at: '2026-09-11T18:43:14+10:00'
---

Use `scripts/install-package NAME...` for explicitly authorized packages from
existing APT repositories. The root-owned wrapper permits named installations, not
arbitrary APT options, local packages, repository changes, removals, upgrades, or
general privileged commands. Inspect its records with
`journalctl -t agent-package-install`.
