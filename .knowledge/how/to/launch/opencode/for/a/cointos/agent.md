---
status: green
revised_at: "2026-09-26T10:52:55+10:00"
---

Agents are OpenCode sessions (`~/.local/bin/opencode`, version 1.18.x) whose model provider is the CointOS gateway.

**Config.** Give each agent an OpenCode config (through the `OPENCODE_CONFIG` environment variable) with:
- one provider using `"npm": "@ai-sdk/openai-compatible"`, whose `baseURL` is the gateway and whose API key is the agent's gateway key;
- the work model declared with `limit.context` equal to its lane size (131,072) and `limit.output` equal to the configured output cap;
- `permission`: `"*": "allow"` inside the agent's worktree and David's home, with web fetch and search, `sudo`, `su`, `systemctl`, package managers and `git push` denied.

David's global config at `~/.config/opencode/opencode.json` registers the knowledge-tree MCP server (`python3 ~/.knowledge/.tools/kt-mcp`) and the knowledge-tree plugin. Agents keep both.

**Launch sequence:**
1. `opencode serve --hostname 127.0.0.1 --port 0 --mdns=false`, with the worktree as working directory. Read the listening URL from its output (`opencode server listening on http://127.0.0.1:PORT`). Do not pass `--pure`: it disables plugins, including the knowledge-tree plugin that injects the agent's startup knowledge.
2. `opencode run --attach URL --dir WORKTREE --title TITLE --model PROVIDER/MODEL`, with the prompt written to the client's **stdin**. `opencode run` wraps any positional message containing spaces in literal quotes; stdin is taken verbatim.
3. To resume an existing session, add `--session SESSION_ID`.
4. `opencode run` emits JSON events on stdout, one per line. `step_finish` marks a completed step, and the session id appears in the events. The server's HTTP API also exposes session messages.

**Watching an agent live:** `opencode attach URL --session SESSION_ID` opens a TUI view of a running session.

**Shell tools in agent sessions:** `rg` (ripgrep) is at `~/.local/bin/rg`, which is on the OpenCode server's `PATH`.

A launcher implementing steps 1–2 (a supervised server, stdin prompt delivery, a process group per agent) is `scripts/opencode_observable.py` at git tag `archive/pre-rebuild` (`where/are/reusable/cointos/parts.md`).
