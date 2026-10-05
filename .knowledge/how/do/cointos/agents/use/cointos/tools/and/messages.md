---
status: green
revised_at: "2026-10-05T13:21:12+11:00"
---

`cointos/mcp.py` is a stdio MCP server that OpenCode starts for each agent run (`python3 -P -m cointos.mcp`, with `PYTHONPATH` at the installed runtime and the run's `COINTOS_TASK_ID`/`COINTOS_AGENT` in its environment; `opencode.settings` adds it as the `cointos` server). OpenCode exposes its tools as `cointos_<name>`.

Each tool builds an argument vector for the matching `cli` command and runs it in-process, so arguments never pass through a shell and the CLI and tools share one implementation. Required arguments are checked before running. The server keeps the real stdout for protocol messages and points file descriptor 1 at stderr, so subprocess output cannot corrupt the stream. Before the tools, about half of agents' shell `cointos queue` calls failed on quoting of long briefs.

A run sees only its role's tools: everyone gets `finish`, `task`, `jobs`, `status`, `send` and `inbox`; integrators add `review`, `land`, `return`, `incorporate` and `queue`; managers add `queue`, `hold`, `revise`, `cancel`, `replace`, `supersede`, `budget` and `merge`; stewards and test auditors add `queue` and `attention`; gardeners, tree auditors and operators add `merge`. The daemon still enforces every permission. `roles/_base.md` tells agents to call `cointos_<command>` wherever instructions name a `cointos <command>`; the shell CLI remains for the user.

**Messages.** The daemon's `send` action puts a short message in an active task's inbox (ledger `messages`, last 200 kept), or alerts the user through Coin for `to: user`. `inbox` returns the asker's unread messages and marks them read. A sender must be the task's current run, or the user's CLI (`cointos message TO "TEXT"`, `cointos inbox`) outside any run. Every tool result except `inbox` ends with an unread-message notice; that is how a busy agent learns of messages, since nothing is injected into a running session. Messages coordinate; work still moves only through the queue and receipts.

Evidence: `tests/test_mcp.py` (role catalogues, a brief with quotes, newlines and shell syntax queued verbatim, protocol list/call, messaging both ways, sender and recipient checks, config wiring). The installed server answered initialize, tools/list and a live status call over real stdio, and `opencode mcp list` with a generated agent config reports `cointos` connected. Use by live agents is not yet observed.
