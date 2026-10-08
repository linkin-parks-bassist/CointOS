---
status: green
revised_at: "2026-10-08T15:19:21+11:00"
---

`cointos/mcp.py` is a stdio MCP server started per OpenCode run (`python3 -P -m cointos.mcp`, installed-runtime `PYTHONPATH`, `COINTOS_TASK_ID`/`COINTOS_AGENT`). OpenCode exposes `cointos_<name>` tools. They run CLI argument vectors in-process without shell quoting, check required arguments and reserve real stdout for protocol messages.

Everyone gets `finish`, `task`, `jobs`, `status`, `peers`, `send` and `inbox`; everyone but workers gets `operator`, which starts an operator paid from the run's own budget (`what/are/the/cointos/roles.md`). Integrators add `review`, `land`, `return`, `incorporate` and `queue`; managers add `queue`, `hold`, `revise`, `cancel`, `replace`, `supersede`, `budget` and `merge`; stewards/test auditors add `queue` and `attention`; gardeners/tree auditors/operators add `merge`. Daemon permissions remain authoritative. New tool definitions reach newly launched runs only. `roles/_base.md` directs concise coordination and no waiting for replies.

`peers` shows other live runs, task IDs, roles, purposes, activity and worktree changes. Message destinations use exact IDs from `cointos jobs`; shortened `agents` labels are invalid.

`send` accepts an active task, `user`, or `mailbox:NAME`. A task sender must own its current run. The local CLI uses `cointos message TO "TEXT"`. The daemon alone writes the ledger, retaining its last 200 messages.

Task messages are posted once to the live OpenCode session as `noReply` user messages via `POST /session/ID/message`; failed posts retry on later daemon ticks. They reach the next model request even mid-turn. `prompt_async` waits until the multi-step turn ends and is unsuitable. `inbox` reads and marks unread messages.

`user` messages alert through Coin and are immediately stored read, so `cointos inbox` does not retrieve those replies. Use a dedicated external mailbox when phone alerts are unwanted:

- Agents send normally to `mailbox:codex` (or another agreed name).
- External clients receive with `cointos inbox --mailbox codex`, or API `inbox` with `{"mailbox":"codex"}`.
- External clients reply as themselves with `cointos message --mailbox codex TASK "TEXT"`.

Mailboxes are local polled identities, not tasks or model runs. They require no registration or extra ledger schema. Names contain letters/digits/underscores/hyphens and start with a letter/digit. Mailbox messages remain unread until collected, produce no Coin alert and are never posted to OpenCode. Agent identities cannot impersonate or read an external mailbox. These are same-user local API controls, not authentication against hostile local processes.

An external client must actually monitor its mailbox. Receipt detection does not wake its harness automatically: keep a monitored tool call active or establish supported harness delivery before promising unattended replies.

Evidence: `cointos/{mcp,api,messages,cli}.py`; `tests/test_mcp.py` covers role catalogues, normal delivery, mailboxes, no alerts, one-time receipt, replies and rejected impersonation. OpenCode 1.18.34 mid-tool delivery and a live three-message operator exchange were separately verified.
