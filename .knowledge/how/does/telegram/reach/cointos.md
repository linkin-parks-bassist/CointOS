---
status: "green"
revised_at: "2026-09-27T00:28:34+10:00"
---

Coin is a separate Telegram service implemented in `cointos/coin.py`. Credentials live in the configured `~/.config/agent-ecosystem/telegram.env`, never in the repository or command-line arguments:
- `AGENT_TELEGRAM_BOT_TOKEN`: bot token.
- `AGENT_TELEGRAM_ALLOWED_USER_IDS`: IDs allowed to talk to Coin.

The service long-polls `getUpdates`, accepts allow-listed text messages and uses `sendMessage` for replies. It persists the next update offset before processing each update. This avoids ordinary replay but is not exactly-once delivery: a crash after offset persistence can lose processing, and sending has no durable delivery acknowledgement in conversation history.

**Routing.**
- Plain `status` or `/status` uses the CLI directly without a model turn.
- Other messages first get a front-desk-model reply through the gateway at Coin priority (one front-model lane is reserved for Coin and Sole Survivor).
- Every non-status message then enters a serial deeper-turn queue on the work model, even if the small model says no deeper turn is needed. The deeper turn can finish silently or send a useful follow-up.
- Deep tools expose status, agents, jobs, checks, queues, pause/resume, stop-agent, start, halt and knowledge-tree tools. Coin's halt uses `--keep-coin`; an ordinary CLI halt stops Coin too.
- The configured tool-round budget is currently 8, followed by up to 3 finishing iterations with terminal tools. Repeated identical calls reuse their earlier result within a turn.
- Recent history keeps the configured last 20 messages per user. Runtime history and offsets are in `state/coin/`. Recorded assistant history precedes sending and alone does not prove delivery.
- A separate loop forwards new daemon alerts to allowed users.

The first model call has a 12-second timeout and a fallback acknowledgement, but network/retry latency still needs measurement. An active service does not prove the spec's visible reply within 15 seconds. Real round-trip and under-load timing remain unestablished in the current acceptance record. Source and service state were checked on 2026-09-27 without sending test messages.
