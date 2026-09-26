---
status: green
revised_at: "2026-09-26T10:52:55+10:00"
---

Coin is a Telegram bot. Its credentials live in `~/.config/agent-ecosystem/telegram.env` (never in the repository or on command lines):
- `AGENT_TELEGRAM_BOT_TOKEN`: the bot token;
- `AGENT_TELEGRAM_ALLOWED_USER_IDS`: the Telegram user IDs allowed to talk to Coin (David).

The bot reads updates with the Telegram Bot API (`getUpdates` long polling) and replies with `sendMessage`. Only allow-listed users are served. The last processed update ID is stored, so messages are handled once.

Coin's turn has two stages:
1. a fast reply from the front-desk model on its reserved lane, within seconds;
2. when the message needs tools or thought, a deeper turn on the work model at Coin priority, which uses the daemon API and knowledge-tree tools and sends a follow-up when it has something new.

Each deeper turn runs a bounded number of tool rounds before replying. Recent conversation (the last 20 messages) is kept per user as context.
