---
status: green
revised_at: "2026-10-10T15:19:52+11:00"
---

Coin is the separate Telegram control service in `cointos/coin.py`. Credentials remain outside the repository in the configured `~/.config/agent-ecosystem/telegram.env` (`AGENT_TELEGRAM_BOT_TOKEN`, `AGENT_TELEGRAM_ALLOWED_USER_IDS`).

Coin long-polls `getUpdates`, accepts allow-listed text and replies with `sendMessage`. It persists the next update offset before processing an update: no ordinary replay, but a crash after persistence may lose that update.

## Turns

- `status` and `/status` are answered mechanically from the control surface, so they work while the work model is down.
- Every other message goes straight to the work model at Coin class, which pre-empts background agents on its lane. There is no front-desk model. One worker runs one turn at a time; messages from the same user that arrive mid-turn join the running turn at its next round.
- The system prompt (`roles/_control-plane.md`) and tools are fixed: no live state or per-turn text. The gateway marks the end of Coin's system message as a shared start, exempt from `scheduler.shared_prefix_tokens`, so each turn restores it instead of reading it cold (`gateway.render_request`). All rounds use the same template options: turning thinking off for one round changes the rendering from its first tokens and destroys reuse.
- The first call should be `send` with a few words as proof of life. Besides the prompt, `PROOF_OF_LIFE` is appended to the newest user message of the live turn; stored history keeps the user's words. The model then uses tools, `send`s results and calls `done`; plain content is sent and ends the turn.
- Budget: `coin.max_tool_rounds` (8) plus `coin.finishing_rounds` (3), in which only `send` and `done` run (other calls get an out-of-steps error; the tool list never changes). Each model call is capped by `coin.model_seconds` (600). A failed turn tells the user why in plain words and that `status` still works.

## Tools

Typed tools cover status, agents, jobs, checks, queue/hold/revise, project registry, scoped operator launch, scout, pause/resume, kill/resume task, halt/start and the reply-draining `restart`; CLI refusals return as tool errors. Killing an agent is run-only control: unfinished work is held uncharged until explicit resume. Of the kt tools Coin sees only `kt_lookup`, `kt_find`, `kt_grep`, `kt_read`, `kt_add`, `kt_rewrite` and `kt_renew`; the kt server's instructions are not injected. Each result answers its exact request ID and name; identical repeated calls reuse their result within a turn. Requests carry the default reasoning effort (low, 256-token cap) and are request-owned, so a disconnected caller's thought is cancelled.

## History and alerts

Per-user history (`state/coin/conversation-*.jsonl`, last `coin.history_messages`) holds user messages, everything Coin sent and forwarded daemon alerts (prefixed ⚠️), so a reply to an alert is intelligible. Tool calls are not kept across turns. Recording precedes sending and does not prove delivery.

`alert_forwarder` records and sends ledger alerts above the integer cursor in `state/coin/alerts-seen.json`, then advances it; with no cursor, startup begins after retained events. Partial delivery then failure can repeat a batch. The daemon owns incident lifetime: one alert per incident, rearmed after 30 seconds of sustained recovery.

## Availability boundary

Measured live through the real gateway with Telegram stubbed: proof of life arrived 11 seconds after the message with the lane free and the shared start restored, about 23–30 seconds when read cold or pre-empting an agent. Whole turns that use tools took 40–150 seconds. Each Coin round on the single work lane saves and later restores an agent's context. While the memory guard has the work model unloaded, only `status` answers. The 15-second target is not reliably met (`what/is/broken.md`).
