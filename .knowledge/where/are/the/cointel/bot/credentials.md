---
status: green
revised_at: "2026-11-15T21:40:33+11:00"
---

Each Cointel instance reads its Telegram bot token from an env-style file named by the `coin.telegram_env` setting in `config/cointos.json`; `cointos/coin.py:credentials()` parses `NAME=value` lines, ignoring blank and comment lines, and strips surrounding quotes.

Two variables are required:

- `AGENT_TELEGRAM_BOT_TOKEN` - the BotFather token. It is the whole credential; never put it in source, the tree, a task brief or a chat message.
- `AGENT_TELEGRAM_ALLOWED_USER_IDS` - one or more numeric Telegram user IDs, comma or space separated, that may use the bot. Any other sender is refused unchanged.

The existing single Coin uses `~/.config/agent-ecosystem/telegram.env`. David created the three instance files on 2026-11-15: `cointelprofessional.env`, `cointelamateur.env` and `cointelpersonal.env`, each holding both variables and all at mode 600 user `david` (they were group/world-readable until corrected). Nothing reads them yet: each installed instance must name its own file in `coin.telegram_env`, and no installed instance exists. A hosted agent must not read the personal file's value; it only needs the path.

Tokens are obtained and rotated through Telegram's BotFather: how/to/create/a/cointel/bot/token.md.
