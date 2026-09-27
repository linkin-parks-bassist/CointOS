---
status: green
revised_at: "2026-09-27T16:58:36+10:00"
---

Run `scripts/install` from the source repository. This standalone script installs a runtime copy at `~/.CointOS/`; installation is not a CointOS CLI subcommand.

Pause first with `cointos stop` and verify there are no agents. The installer refuses active agent units or an unpaused live daemon. It stops cointosd and Coin before copying code, roles, web, bin, systemd and config. On first installation it migrates source runtime state after shutdown, excluding worktrees; later installs preserve installed state and knowledge. It refuses an unmarked existing installation, which must be archived first. It initializes a separate runtime knowledge tree when absent, writes service units targeting the installed directory, updates `~/.local/bin/cointos`, reloads systemd and enables the services. It leaves services stopped; `cointos up` starts them without clearing pause. A new ledger defaults to paused.

The runtime tree must be registered as globally readable through kt access approval. The daemon alone writes scheduler records and publishes the current task and command queues there. Project trees are independent. Worktrees live in `~/Projects/.worktrees/<project>/<task>` on `work/<task>` branches, never under the runtime.

The pre-rebuild installation and its 20 legacy unit files were archived to `~/.local/share/cointos-pre-rebuild-20260927-164834.tar.gz`, then removed; its old kt registration and grants were revoked. This archive does not contain the replacement runtime.

Source evidence: `scripts/install`, `cointos/config.py`, `cointos/state.py` and `cointos/work.py`. Verify service WorkingDirectory and pause/no-agent state after starting an installed version.
