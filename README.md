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
this milestone. See `docs/operations.md` for setup and the pause switch.

Roles live as readable Markdown in `roles/`. `enqueue` plus `prepare-next` compiles
a role and task into the exact context packet a future local executor will receive.
