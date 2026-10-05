---
status: green
revised_at: "2026-10-05T21:25:27+11:00"
---

Run `scripts/install` from the source repository. It is a standalone installer for `~/.CointOS`, not a CointOS CLI subcommand. The target must either be absent or contain the `.runtime-install` marker.

## Paused full installation

Use `scripts/install` for first installation or any change that invalidates surviving gateway/model processes. Pause CointOS and wait for all agent units to exit. The installer refuses an active unpaused runtime or remaining agent units, stops Coin and cointosd, copies `cointos/`, `roles/`, `web/`, `bin/`, `systemd/` and `config/`, runs the idempotent `scripts/upgrade-ledger`, renders/enables user units, and updates `~/.local/bin/cointos`. It preserves installed `config/projects.json`, because project enrollment is user-managed runtime state rather than a source default. Services remain stopped and pause state is preserved; use `cointos up`, verify `cointos check`, then `cointos go` when autonomy should resume.

The runtime code contains no schema-compatibility branches. `scripts/upgrade-ledger` is the sole migration boundary and refuses legacy running/review work that cannot be converted safely.

## Compatible live installation

Use `scripts/install --live [--wait-seconds N]` (default 60, honoured as given) when the current daemon is reachable and the candidate preserves the process-identity projection owned by `cointos.config.live_incompatibilities`: backend, Lemonade endpoint, snapshot directory, server cgroup, gateway port, work-model identity and model topology/shape. The installer checks that projection before contacting the daemon. Run one installation at a time: each copies whatever the source tree holds when its drain completes.

If nothing the daemon runs changed (`cointos/`, `config/` other than `projects.json`, `systemd/`), the installer copies `roles/`, `web/` and `bin/`, rewrites the runtime leaves and stops: prompts, the dashboard and the CLI are read fresh from disk, so the daemon keeps running untouched.

Otherwise it asks the daemon to quiesce: new model requests wait at the admission gate, no queued reply is given a lane, and the drain is ready once no landing is validating and no reply holds a lane or is producing output. Replies still queued for a lane have produced nothing; when cointosd stops, their stream is cut and OpenCode retries them within about a second (verified against OpenCode 1.18.34). A reply already reading or generating on the lane finishes first, since cutting a reader throws its read away. At that boundary it stops only cointosd, copies and upgrades the runtime, reloads units, restarts cointosd and adopts the surviving Coin, agent and model processes, without relaunching conversations. Timeout, Ctrl-C or an API failure during the drain cancels quiescence before anything is copied (a backgrounded installer ignores SIGINT; terminating it leaves quiescence on until `cancel-restart` or the next daemon start); a later failure after cointosd stops restarts it on exit. An ordinary `cointos restart` still waits for every admitted request. Never pause agents (`cointos stop`) to hurry an installation: it relaunches every conversation.

A live installation preserves Coin's imported code and startup configuration. When those change, finish deployment with a separate quiet Coin refresh as below.

## Isolated service changes

The gateway reads `web/dashboard.html` from the installed runtime on every request, so a dashboard-only change deploys by copying that file; ship it with the installer instead when it depends on daemon changes, so page and daemon never disagree. A change confined to `cointos/coin.py` can deploy by copying it and restarting only `cointos-coin.service` once Coin has no outstanding gateway thought or pending conversation work. Isolated copies avoid shipping unrelated uncommitted source changes.

## Runtime knowledge and registry

Each installation replaces the installed tree's `where/am/i.md` and `what/is/cointos.md` with `runtime/where-am-i.md` and `runtime/what-is-cointos.md` through `cointos/kt.py`, which writes generated leaves (also the daemon's queue answers) with the CLI-only `kt rewrite --force`. Edit the source files, not their generated copies. The runtime tree requires its explicit globally readable kt registration; project trees remain independent.

Worktrees live at `~/Projects/.worktrees/<project>/<task>` on `work/<task>` branches. After every installation verify that the installed copy contains the change, service state, adopted agent identities when live installing, and `cointos check`.
