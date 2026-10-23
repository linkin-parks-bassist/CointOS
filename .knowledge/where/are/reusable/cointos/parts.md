---
status: green
revised_at: "2026-10-14T23:13:12+11:00"
---

This is an archive reference. The current module map is where/are/cointos/source/modules.md; architecture is the broad system overview. Current responsibilities live in cointos/opencode.py, kt_mcp.py, coin.py, cli.py and web/dashboard.html; installation uses scripts/install. Consult those first.

At Git tag archive/pre-rebuild, all eight paths below are verified present and remain useful historical comparisons (git show archive/pre-rebuild:PATH):

- scripts/opencode_observable.py starts private loopback servers, prompts over stdin and supervises process groups/live viewers; its admission/capacity dependencies are old core.
- ecosystem/knowledge_tools.py is a minimal stdio knowledge-tree MCP client; the current equivalent is cointos/kt_mcp.py.
- ecosystem/control_agent.py contains Coin's bounded tool loop, repeated-call detection and terminal tools.
- ecosystem/web/dashboard.html holds the earlier blush-paper/ink/rose palette, role-coloured lanes, agents, Coin, project queues and recent jobs. It polls a snapshot every two seconds; the current dashboard uses the daemon ledger/live stream.
- ecosystem/views.py renders terminal status/agents/jobs; current CLI ownership is cointos/cli.py.
- ecosystem/conversation.py maintains per-user JSONL Telegram history.
- survival/telegram_api.py implements long polling, sends and allow-list.
- scripts/install-cointos copies the source into the runtime prefix and renders user-service units.

These files do not describe current runtime behavior.
