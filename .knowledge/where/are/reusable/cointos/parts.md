---
status: "green"
revised_at: "2026-09-27T00:28:59+10:00"
---

This is an archive reference, not the current runtime map. The corresponding responsibilities now live in `cointos/agents.py`, `kt_mcp.py`, `coin.py`, `cli.py` and `web/dashboard.html`; installation uses `scripts/install`. Consult those first. The old files remain available for historical comparison.

These parts, at git tag `archive/pre-rebuild` (read one with `git show archive/pre-rebuild:PATH`), record the earlier implementations (all eight paths verified present in the tag):

- `scripts/opencode_observable.py`: starts an OpenCode server per agent on loopback, delivers the prompt through stdin, supervises the process group, and exposes a live view URL. Its admission and capacity dependencies belong to the old core.
- `ecosystem/knowledge_tools.py` (about 100 lines): a minimal stdio MCP client that starts `~/.knowledge/.tools/kt-mcp` and exposes its `kt_*` tools as function-calling schemas. The current Coin uses `cointos/kt_mcp.py`.
- `ecosystem/control_agent.py`: Coin's deep-turn tool loop, with bounded tool rounds, repeated-call detection and terminal tools (`publish_followup`, `finish_silently`).
- `ecosystem/web/dashboard.html`: the dashboard page, styled after David's website (`~/Projects/Website/style.css`). It shows a live stage of model lanes with agents as role-coloured orbs, an agents panel, a Coin panel, per-project queue boards and a recent-jobs strip. It polls one JSON snapshot every 2 s; the current dashboard instead uses the daemon ledger and live stream.
- `ecosystem/views.py`: renders the terminal views (`cointos status`, `agents`, `jobs`); the current CLI is `cointos/cli.py`.
- `ecosystem/conversation.py`: per-user Telegram conversation history (JSONL, last N messages as context).
- `survival/telegram_api.py`: a Telegram Bot API client (long polling, sending, allow-list).
- `scripts/install-cointos`: copies the source into the runtime prefix `~/.CointOS` and renders the systemd user units.
