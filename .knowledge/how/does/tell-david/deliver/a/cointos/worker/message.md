---
status: green
revised_at: "2026-09-26T00:38:31+10:00"
---

`ecosystem tell-david --message '...'` is a worker-facing installed CLI command. It requires `AGENT_TELEGRAM_ALLOWED_USER_IDS` in its environment; for each configured recipient it writes a durable `outbound-message` job under the installed `~/.CointOS/state/jobs/` and prints that outbox ID. `AGENT_JOB_ID`, when present, is recorded as `origin_job`. Options are `--severity info|warning|question|approval` (default `info`) and `--needs-response`. Warning/question/approval add a visible prefix; `--needs-response` appends a natural-reply invitation. The call queues a message; it does not synchronously send Telegram or await David's reply.

The installed `agent-notifier.service` polls the outbox, presents the text using recent conversation context, then sends it through the configured Telegram bot and records delivery. A failed/uncertain send is represented durably; an uncertain delivery must not be blindly replayed. `--needs-response` is a conversational request, not a guarantee that the original worker will block and resume on the reply. For a quick status check use the returned outbox job ID with the read-only job inspector, not another send.
