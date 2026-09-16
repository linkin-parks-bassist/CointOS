---
scope: project local
source: "explicit activation; fresh systemctl/journal; real installed work and default control inference; runtime cleanup evidence 2026-09-14"
review_when: Recheck after persisted-state layout, service names, or backend endpoints change.
status: "unverified"
updated_at: "2026-09-14T23:57:45+10:00"
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

Current installation audit 2026-09-14: current code/assets are deployed into ~/.CointOS. Four divergent KT spine owners were reconciled revision-safely; reviewed runtime constraints are retained. Eleven rendered service/path/timer definitions were backed up and adopted under ~/.config/systemd/user, then daemon-reloaded. Loaded ecosystem/Telegram/control/watchdog/proxy commands and working directories now target ~/.CointOS. Installed CLI and proxy --help checks pass. Source-derived cli.ROOT resolves the installed root when imported from that installation.

Services were activated at David explicit request. Proxy, Telegram gateway, control workers, notifier, resource guard, inbox path and ecosystem/watchdog timers are active, with zero observed restart counts. Ecosystem and watchdog oneshots complete successfully and then return inactive/dead. Historical queued tasks missing routing metadata remain deferred. Startup compatibility defects in status sidecar enumeration and missing/null legacy authority were repaired and deployed.

agent-models was restarted to restore pinned Qwen3.5-4B, now two 16384-token sequences, while preserving Qwen3.8-27B at one 131072-token slot. Installed managed work inference returned READY, with released sequence and quiescent worker verified. Default fast control inference returned visible text locally. No test Telegram message was sent. Startup/basic inference is verified; saturated priority, Telegram exchange and restart recovery remain outstanding. See what/is/broken.md and how/were/installed/cointos/services/brought/online.md.
