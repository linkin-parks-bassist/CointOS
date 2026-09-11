---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local
source: git show fe92546:docs/operations.md; current scripts and runtime-root decision
verification: Checked named repository entry points; commands affecting stopped or root-owned services were not executed.
review_when: Recheck when CLI commands, service installation, or runtime layout changes.
---

Run one manual intake pass with `./scripts/ecosystem run-once` and inspect queue
counts with `./scripts/ecosystem status`. Pause new automatic work with
`./scripts/ecosystem pause`; resume only after checking current runtime state. Live
state and append-only run evidence are under `~/.CointOS`, not the checkout.

Repository-owned user units under `services/systemd/` are development
infrastructure. Do not copy, enable, restart, or treat them as live without explicit
task authority and fresh service-state checks. The root-owned survival-plane
installer is `scripts/install-survival-plane`; its default is install-only, while
activation is a separate consequential operation. Credentials belong in their
documented protected system locations and never on command lines. Use `sudo -A`
when David is at the workstation and elevation is explicitly within scope.

For diagnosis, query only the relevant combination of `systemctl --user`, current
process identity, `~/.CointOS/state`, `~/.CointOS/logs`, and the loopback Lemonade
health endpoint. An active unit or zero exit status is not proof of a correct
outcome. Never rewrite JSONL while reconciling it.
