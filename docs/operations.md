# Operations

## Manual operation

Run `./scripts/ecosystem run-once`. `status` reports queue counts. Inputs are
accepted only as `inbox/new/*.md`. A SHA-256-derived job ID makes rescanning the
same content idempotent.

Use `./scripts/ecosystem pause` as the global kill switch. While paused,
`run-once` exits with status 75 before scanning or processing. Use `resume` to
clear it.

Failed work remains in `state/jobs/*.json`; the current CLI does not retry it
automatically. This is deliberate until retry limits and operator controls are
implemented. Logs in `logs/runs/YYYY-MM-DD.jsonl` are append-only.

## Optional systemd user units

The checked-in units have not been installed or enabled. After explicit approval:

```bash
mkdir -p ~/.config/systemd/user
cp services/systemd/agent-ecosystem.{service,path,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-ecosystem.path agent-ecosystem.timer
```

Stop all automatic intake with:

```bash
./scripts/ecosystem pause
systemctl --user stop agent-ecosystem.path agent-ecosystem.timer
```

Inspect with `systemctl --user status agent-ecosystem.path
agent-ecosystem.timer` and `journalctl --user -u agent-ecosystem.service`.

## Roles and remote spawning

Roles are Markdown files in `roles/`. A valid role includes `Mission`,
`Permissions`, `Approval required`, and `Handoff` headings. Test context injection:

```bash
./scripts/ecosystem enqueue --role worker --task "Inspect project X and propose its first test"
./scripts/ecosystem prepare-next
```

The resulting `state/jobs/*.prompt.md` is the exact context packet intended for
an executor. No executor is wired yet, so remote input cannot silently execute code.

The Telegram gateway uses outbound long polling and accepts only configured user
IDs. Put the following in `~/.config/agent-ecosystem/telegram.env` with mode `0600`:

```text
AGENT_TELEGRAM_BOT_TOKEN=replace-me
AGENT_TELEGRAM_ALLOWED_USER_IDS=123456789
```

It supports `/spawn ROLE TASK`, `/roles`, `/status`, and `/pause`; arbitrary text
is never shell input. Installing/enabling `agent-telegram.service` waits for an
explicit decision on credentials and remote data handling.
