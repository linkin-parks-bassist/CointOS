---
status: green
revised_at: "2026-09-28T17:13:41+10:00"
---

Use `cointos agents` and `cointos jobs --all` for the live identity and task state. The exact run directory is `~/.CointOS/state/agents/<agent-id>/`: `run.json` contains the task and launch prompt, `events.jsonl` contains streamed OpenCode events, and `server.json` contains the child server PID while it is live. The child server process environment must contain `COINTOS_TASK_ID=<exact system task id>`; this is how `cointos queue` attributes and restricts steward proposals. Use `journalctl --user -u cointos-agent-<agent-id>.service` for launch failures. A healthy live steward appears in `cointos agents`, and `cointos check` remains green.
