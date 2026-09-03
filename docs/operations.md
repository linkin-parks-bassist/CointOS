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

The resulting `state/jobs/*.prompt.md` is the exact context packet passed to the
serialized OpenCode executor. It runs as David (never root), uses Lemonade locally,
and records output in `logs/runs/<job-id>.opencode.log`.

The executor may modify David-owned files. Its dedicated OpenCode policy blocks
obvious privilege, package-management, service-management, destructive deletion,
Git push, and web tools. Shell containment is best-effort rather than a security
boundary; elevated actions will move through a separate approval broker.
Completion and failure summaries are durable `outbound-message` jobs dependent on
the agent job reaching a terminal state. The Telegram gateway drains this outbox,
retries transient delivery failures, and returns the useful tail of agent output;
the complete transcript remains on disk. This same dependency mechanism is the
foundation for future state watchers and scheduled reminders.

The Telegram gateway uses outbound long polling and accepts only configured user
IDs. Put the following in `~/.config/agent-ecosystem/telegram.env` with mode `0600`:

```text
AGENT_TELEGRAM_BOT_TOKEN=replace-me
AGENT_TELEGRAM_ALLOWED_USER_IDS=123456789
```

It supports `/spawn ROLE TASK`, `/roles`, `/status`, and `/pause`; arbitrary text
is never shell input. Installing/enabling `agent-telegram.service` waits for an
explicit decision on credentials and remote data handling.

Ordinary English is routed by a locally served control-plane model into
one of five validated intents: spawn, status, roles, pause, or chat. The model
cannot emit shell operations or bypass role validation. Override the local routing
model with `AGENT_TELEGRAM_MODEL` in the protected environment file.

The installed gateway uses the smaller `Qwen3.5-4B-GGUF` as a dedicated control
plane model. It acknowledges natural-language messages before inference and only
advances the Telegram update offset after successful handling. Long worker jobs
therefore do not monopolize remote control.

The bot stores a private per-user JSONL conversation under `state/conversations/`
and supplies at most the latest 20 messages / 12,000 characters to GLM. This lets
follow-ups refer to prior discussion without putting chat history in Git or audit
events. `/forget` clears conversational memory without deleting jobs or audit logs.
Corrections to the most recent queued/prepared task use the validated `amend`
intent and regenerate its context. Running or completed jobs are never rewritten.

For first-time users, `./scripts/setup-telegram` walks through bot creation,
validates the token, discovers the user ID from a message, and writes the protected
environment file. It does not enable the gateway.
