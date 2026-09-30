---
status: green
revised_at: "2026-09-30T10:31:18+10:00"
---

Coin is the separate Telegram control service in `cointos/coin.py`. Credentials remain outside the repository in the configured `~/.config/agent-ecosystem/telegram.env`:

- `AGENT_TELEGRAM_BOT_TOKEN`
- `AGENT_TELEGRAM_ALLOWED_USER_IDS`

Coin long-polls `getUpdates`, accepts allow-listed text and sends replies with `sendMessage`. It persists the next update offset before processing an update, preventing ordinary replay but not providing exactly-once delivery: a crash after offset persistence may lose that update. Assistant history is recorded before sending and therefore does not prove Telegram delivery.

## Routing

- `status` and `/status` use the control surface directly without inference.
- Every other message first receives a short front-model reply through the gateway at Coin priority on its reserved lane. A deterministic formatter removes a trailing engagement question from a multi-sentence fast reply; it preserves a single-question reply.
- Every non-status message then enters the serial work-model deep-turn queue. The deep turn may send a useful follow-up or finish silently.
- Daemon alerts are forwarded separately to allowed users.

The deep turn uses typed tools for status, agents, jobs, checks, queue/task controls, project registry, lifecycle controls, scoped operator launch and knowledge-tree access. Each model tool request is answered with a `tool` message carrying that exact request ID and tool name. Repeated identical calls reuse their result within the turn. The configured round budget is eight ordinary tool rounds plus up to three terminal finishing rounds.

Killing an agent through Coin is run-only control: unfinished work is held uncharged with artifacts preserved until explicit task resume. Coin does not infer task completion from processes or text.

Recent per-user conversation history is stored under `state/coin/` and limited by `coin.history_messages`. Update offsets are stored there too.

## Availability boundary

The fast model call has a configured 12-second timeout and a fallback acknowledgement. Network calls and Telegram retries can still exceed the MVP's visible-reply target; an active service alone is not proof. The deep tool/result identity path is unit-covered and installed, but a real post-fix Telegram deep-tool exchange and ten-message under-load latency measurement remain unproved in `what/is/the/plan.md`.
