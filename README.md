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
