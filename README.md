# Agent Ecosystem

An inspectable, local-first agent workbench. The first vertical slice turns a
Markdown file dropped into `inbox/new/` into a durable queue entry and a project
proposal under `projects/`, with an append-only JSONL audit trail.

## Quick start

```bash
./scripts/ecosystem init
cp examples/idea.md inbox/new/my-idea.md
./scripts/ecosystem run-once
./scripts/ecosystem status
```

The default CLI path does not contact the network, start an agent model, or change
user services. The optional Telegram gateway is the sole networked component in
this milestone. Operational knowledge is under `.knowledge/how/to/operate/`.

Roles live as readable Markdown in `roles/`. `enqueue` plus `prepare-next` compiles
a role and task into the exact context packet a future local executor will receive.

## Install CointOS

From the development checkout:

```bash
./scripts/install-cointos
```

This copies executable modules/scripts, configuration, role prompts, service
and infrastructure templates, task cards and project knowledge into `~/.CointOS`.
It registers the installed knowledge root as `cointos` with independently installed
`kt`. Installing CointOS automatically grants lookup access to this installed
knowledge root from all projects, including when run noninteractively by agents.

Use `--dry-run` to preview or `--prefix /absolute/path` for an isolated installation.
Use `--no-register` when testing without changing KT root registration.
The installer leaves state, logs, credentials and other operational data alone.
Edited configuration is preserved with new defaults alongside as `.dist` files;
runtime knowledge edits/new leaves are preserved, and conflicting edits in both
source and installed knowledge stop the upgrade before application replacement.
The source revision and local modifications are recorded in `.cointos-install.json`.
One previous application payload is retained in `.cointos-previous` for manual recovery.

Install at a drained service boundary when upgrading: replacement is staged with
rollback on handled replacement errors, but is not an atomic live-code switch.
The installer copies service templates; it does not enable services, restart
processes, install privileged resource controls or deploy model weights.
Installed commands can be called from any directory, for example
`~/.CointOS/scripts/ecosystem --help`.
For the default `~/.CointOS` prefix, installation also links `ecosystem`,
`cointos` (an alias for `ecosystem`), `cointos-jobs`, `cointos-job-info`,
`cointos-profile`, `cointos-health`, and `cointos-incident`
into `~/.local/bin`. Ensure that directory is on your shell `PATH` to run
`ecosystem status` or `cointos-jobs --active` from anywhere. Existing unrelated
commands are never replaced. Use `--no-path-links` to skip these links, or
`--bin-dir /absolute/path` to link a custom installation into another directory.
`./scripts/install-cointos --links-only` exposes an existing default installation
without replacing its running code or restarting services.

`cointos-health` reads the installed resource gate, loaded model recipes, and
worker/inference/proxy lease-state counts without changing them. Add `--json` for
machine-readable output; it does not display job prompts or worker output.
`cointos-incident [INCIDENT_ID] --json` gives a bounded view of one immutable
resource-incident snapshot and its current gate, without dumping large one-line
ledgers or asserting that recovery is safe. Omit the ID to inspect the current
incident; use `cointos-health` for current backend and lease counts.

`cointos-profile status` shows the resident physical slot profile and its exact
qualified ceiling. `cointos-profile plan` shows the current demand, dwell and
qualification decision without reloading a model. `qualify-current` records a reviewed live capability;
`resize-qualified` performs a fenced manual transition. Automatic profile
reconciliation remains off until `cointos-profile enable-automation` is run after
live transition qualification. `disable-automation` stops future automatic
profile changes without interrupting current inference.
