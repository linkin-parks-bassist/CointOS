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

Install or refresh the checked-in units with:

```bash
mkdir -p ~/.config/systemd/user
cp services/systemd/agent-ecosystem.{service,path,timer} ~/.config/systemd/user/
cp services/systemd/agent-watchdog.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-ecosystem.path agent-ecosystem.timer agent-watchdog.timer
```

Stop all automatic intake with:

```bash
./scripts/ecosystem pause
systemctl --user stop agent-ecosystem.path agent-ecosystem.timer agent-watchdog.timer
```

Inspect with `systemctl --user status agent-ecosystem.path
agent-ecosystem.timer agent-watchdog.timer` and `journalctl --user -u
agent-ecosystem.service -u agent-watchdog.service`.

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
plane model. Fast responses have no acknowledgement preamble; a restrained progress
message appears only when interpretation exceeds fifteen seconds. It only
advances the Telegram update offset after successful handling. Long worker jobs
therefore do not monopolize remote control.

Machine-status questions have a deterministic local fast path rather than relying
on model knowledge. Status includes active job identity, role, selected model,
elapsed time, output-idle time, and a possible-stall warning after five minutes.
User-facing status is rendered as ordinary prose; the detailed structured version
is retained for control-plane context. All natural-language actions—including
status, roles, and pause—are retained in conversation memory with the actual reply.

The bot's durable identity and operating knowledge live in
`roles/_control-plane.md`. The underscore marks it as infrastructure rather than a
spawnable worker role. Every natural-language turn combines that complete role
with conversation history, live queue status, resources, model residency, and the
model scheduling policy. Spawned agents receive their role plus a concise ecosystem
situation preamble and their recorded model decision.

Periodic Steward instances draw one assignment from `steward-tasks/*.md`. Selection
is randomized with overdue weighting and per-card maximum intervals, providing
variation without proliferating roles or neglecting low-frequency maintenance.
The chosen card, overdue ratio, job, and findings are recorded in watchdog state
and append-only audit events.

All main roles can call `scripts/tell-david` to create a durable agent-originated
outbox message with severity and an optional response requirement. Executor jobs
receive their job ID through `AGENT_JOB_ID`, so messages are traceable. Delivered
messages are appended to the private bot conversation, allowing David's natural
reply to be interpreted with the originating question or warning in context.
Before delivery, the pinned control model rewrites internal notifications into a
concise informal message. Job IDs, raw JSON, log paths, tool chatter, and queue
jargon remain in local records unless David explicitly asks for technical detail.

Each Telegram-spawned job receives a name invented by the control-plane model under
`config/naming-policy.json`. The generator sees active names, honors explicit user
choices, and targets a modest 8% tasteful-odd-name rate without a fixed pool.
The ordinary baseline is intentionally international rather than Anglocentric;
rare variants include pronounceable alien names and genuinely clever task-linked
puns. The policy explicitly rejects cultural caricature, lazy wordplay, and mascot energy.
Non-Telegram jobs use the same pinned control model to generate their identity.
Names are validated before use. Identity is injected
into context and retained through retries, audit events, agent-originated messages,
and completion notices; it does not create a separate role or pretend agents are human.

For every spawn, the control-plane model receives a live inventory of downloaded
models, capability labels, sizes, context limits, loaded/busy state, available
memory, and host load. It selects a model (or honors David's explicit selection),
and the job permanently records both the choice and rationale. The executor does
not choose or hardcode a different model later.

The bot stores a private per-user JSONL conversation under `state/conversations/`
and supplies at most the latest 20 messages / 12,000 characters to GLM. This lets
follow-ups refer to prior discussion without putting chat history in Git or audit
events. `/forget` clears conversational memory without deleting jobs or audit logs.
Corrections to the most recent queued/prepared task use the validated `amend`
intent and regenerate its context. Running or completed jobs are never rewritten.

For first-time users, `./scripts/setup-telegram` walks through bot creation,
validates the token, discovers the user ID from a message, and writes the protected
environment file. It does not enable the gateway.
