---
status: green
revised_at: "2026-09-30T10:25:49+10:00"
---

Run `scripts/install` from the source repository. It is a standalone installer for `~/.CointOS`, not a CointOS CLI subcommand. The target must either be absent or contain the `.runtime-install` marker.

## Paused full installation

Use `scripts/install` for first installation or any change that invalidates surviving gateway/model processes. Pause CointOS and wait for all agent units to exit. The installer refuses an active unpaused runtime or remaining agent units, stops Coin and cointosd, copies `cointos/`, `roles/`, `web/`, `bin/`, `systemd/` and `config/`, runs the idempotent `scripts/upgrade-ledger`, renders/enables user units, and updates `~/.local/bin/cointos`. It preserves installed `config/projects.json`, because project enrollment is user-managed runtime state rather than a source default. Services remain stopped and pause state is preserved; use `cointos up`, verify `cointos check`, then `cointos go` when autonomy should resume.

The runtime code contains no schema-compatibility branches. `scripts/upgrade-ledger` is the sole migration boundary and refuses legacy running/review work that cannot be converted safely.

## Compatible live installation

Use `scripts/install --live [--wait-seconds N]` when the current daemon is reachable and the candidate preserves the process-identity projection owned by `cointos.config.live_incompatibilities`: backend, Lemonade endpoint, snapshot directory, server cgroup, gateway port, work-model identity and model topology/shape.

The installer checks that projection before contacting the daemon, so missing or incompatible installed configuration causes no network or systemd action and reports the exact changed paths. Daemon-policy changes such as reasoning, recovery, scheduling and spawning are compatible.

A live install asks the current daemon to quiesce: admitted thoughts and landing validations finish, while new thoughts receive retryable admission failures. At a quiet request boundary it stops only cointosd, copies and upgrades the runtime, reloads units, restarts cointosd and adopts the surviving Coin, agent and model processes. It does not relaunch agent conversations or inject continuation messages. Timeout or Ctrl-C cancels quiescence before copying or stopping anything. If a later installation step fails after cointosd stops, process-exit cleanup starts the daemon again.

## Runtime knowledge and registry

Each installation rewrites the installed tree's `where/am/i.md` and `what/is/cointos.md` from `runtime/where-am-i.md` and `runtime/what-is-cointos.md` through `cointos/kt.py`; edit those source files, not their generated copies. Other runtime leaves and daemon-published queue answers remain. The runtime tree requires its explicit globally readable kt registration; project trees remain independent.

Worktrees live at `~/Projects/.worktrees/<project>/<task>` on `work/<task>` branches. Verify the installed unit `WorkingDirectory`, service state, exact adopted agent identities when live installing, and `cointos check` after every installation.
