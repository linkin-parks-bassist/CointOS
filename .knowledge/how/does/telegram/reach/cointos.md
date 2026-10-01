---
status: green
revised_at: "2026-10-02T04:07:48+10:00"
---

Coin is the separate Telegram control service in `cointos/coin.py`. Credentials remain outside the repository in the configured `~/.config/agent-ecosystem/telegram.env`:

- `AGENT_TELEGRAM_BOT_TOKEN`
- `AGENT_TELEGRAM_ALLOWED_USER_IDS`

Coin long-polls `getUpdates`, accepts allow-listed text and sends replies with `sendMessage`. It persists the next update offset before processing an update, preventing ordinary replay but not providing exactly-once delivery: a crash after offset persistence may lose that update. Assistant history is recorded before sending and therefore does not prove Telegram delivery.

## Routing

- `status` and `/status` use the control surface directly without inference.
- Every other message shares `coin.reply_seconds` (currently 12 seconds) between its control-state lookup and front-model call. The lookup is capped by the lesser of that budget and the API timeout; the model gets only the remaining time. If none remains, Coin acknowledges without starting inference. It first sends a short front-model reply through the gateway at Coin priority on its reserved lane. A deterministic formatter removes a trailing engagement question from a multi-sentence fast reply; it preserves a single-question reply.
- Every non-status message then enters the serial work-model deep-turn queue. The deep turn may send a useful follow-up or finish silently.
- Daemon alerts are forwarded separately to allowed users. A self-check sends one alert per incident; only 30 seconds of sustained recovery rearms that check. The daemon persists notification incident state across replacement, while the dashboard retains current details.

## Alert delivery frontier

Inspect pending alert forwarding by comparing the ledger's retained alert IDs with the integer cursor in `state/coin/alerts-seen.json`. The alert records themselves have no per-event acknowledgement field; retained old events are not an unread backlog. `alert_forwarder` selects IDs greater than its cursor and advances the saved cursor after forwarding the batch to the configured users. With no saved cursor, startup begins after the retained events rather than replaying them. This cursor is forwarding state, not exactly-once delivery evidence; partial delivery followed by a failure can cause a retry.

Coin model requests explicitly carry the configured default reasoning effort (currently low) unless that call overrides it. The gateway therefore applies the same uninterrupted reasoning cap (256 tokens at low) as it does for managed tasks; deep control turns cannot silently fall back to uncapped model-default reasoning. The front reply still disables thinking.

Coin's JSON model requests are request-owned: the gateway detects peer EOF while waiting, cancels disconnected callers and releases an in-flight thought at its step boundary. Coin thoughts are included in the 60-second no-progress check. Backend token steps preserve UTF-8 fragments without allowing text-parser errors or truncated replies to become a lane replay loop.

The deep turn uses typed tools for status, agents, jobs, checks, queue/task controls, project registry, lifecycle controls, scoped operator launch and knowledge-tree access. Its `restart` tool uses the CLI's reply-draining daemon replacement, preserving agent sessions and loaded models; CLI refusals are returned as tool errors rather than terminating Coin's deep worker. Each model tool request is answered with a `tool` message carrying that exact request ID and tool name. Repeated identical calls reuse their result within the turn. The configured round budget is eight ordinary tool rounds plus up to three terminal finishing rounds.

Killing an agent through Coin is run-only control: unfinished work is held uncharged with artifacts preserved until explicit task resume. Coin does not infer task completion from processes or text.

Recent per-user conversation history is stored under `state/coin/` and limited by `coin.history_messages`. Update offsets are stored there too.

## Availability boundary

First-reply preparation has one configured 12-second budget for lookup plus inference, with a fallback acknowledgement. Status-only requests use the same capped control lookup. This removes the former sequential 10-second lookup plus 12-second model allowance. Network calls and Telegram retries can still exceed the MVP's visible-reply target; an active service alone is not proof. The deep tool/result identity path is unit-covered and installed, but a real post-fix Telegram deep-tool exchange and ten-message under-load latency measurement remain unproved in `what/is/the/plan.md`.
