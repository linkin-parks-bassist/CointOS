---
status: "green"
revised_at: "2026-09-26T10:53:35+10:00"
---

These parts, at git tag `archive/pre-rebuild` (read one with `git show archive/pre-rebuild:PATH`), do jobs the architecture still needs and are small enough to lift and adapt:

- `scripts/opencode_observable.py`: starts an OpenCode server per agent on loopback, delivers the prompt through stdin, supervises the process group, and exposes a live view URL. Its admission and capacity imports go away; it becomes the agent launcher.
- `ecosystem/knowledge_tools.py` (about 100 lines): a minimal stdio MCP client that starts `~/.knowledge/.tools/kt-mcp` and exposes its `kt_*` tools as function-calling schemas. Coin uses it.
- `ecosystem/control_agent.py`: Coin's deep-turn tool loop, with bounded tool rounds, repeated-call detection and terminal tools (`publish_followup`, `finish_silently`).
- `ecosystem/web/dashboard.html`: the dashboard page, styled after David's website (`~/Projects/Website/style.css`). It shows a live stage of model lanes with agents as role-coloured orbs, an agents panel, a Coin panel, per-project queue boards and a recent-jobs strip. It polls one JSON snapshot every 2 s; point it at the new ledger.
- `ecosystem/views.py`: renders the terminal views (`cointos status`, `agents`, `jobs`); its layout carries over to the new ledger.
- `ecosystem/conversation.py`: per-user Telegram conversation history (JSONL, last N messages as context).
- `survival/telegram_api.py`: a Telegram Bot API client (long polling, sending, allow-list).
- `scripts/install-cointos`: copies the source into the runtime prefix `~/.CointOS` and renders the systemd user units.
