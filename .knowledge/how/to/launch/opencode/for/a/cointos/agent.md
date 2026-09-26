---
status: "green"
revised_at: "2026-09-27T00:59:57+10:00"
---

Agents are OpenCode sessions whose provider is the CointOS gateway. The installed binary is `~/.local/bin/opencode`, checked as version 1.18.32 on 2026-09-27. The implementation is `cointos/agents.py`.

**Config.** Each run receives an `OPENCODE_CONFIG` file under `state/agents/<id>/`, created mode 0600 for its gateway key:
- Provider `cointos` uses `@ai-sdk/openai-compatible`, the gateway's `/v1` endpoint and the agent key.
- `timeout`, `headerTimeout` and `chunkTimeout` are false. Earlier default 300,000 ms timeouts aborted waiting/prefilling requests; daemon lifecycle rules handle stalled agents. The 30-second event-silence bound applies when no thought is outstanding, including startup; active model reads/generation and lane waits are exempt. Long tools without an OpenCode event can reach this bound.
- Context limit is configured total context divided by lane count (currently 131,072); output is `max_thought_tokens` (currently 16,384).
- Permissions broadly allow work while denying web fetch/search, doom loops, privilege/package-management commands, `git push`, and `cointos halt|up|stop`. External-directory access permits the home tree except `~/Avnet`; reads deny `*.env` and Avnet, and edits deny Avnet. These are OpenCode permissions, not OS isolation.
- Other global MCP servers are disabled in the per-agent config; knowledgetrees is retained. Sharing and autoupdate are disabled.

The global config registers `python3 ~/.knowledge/.tools/kt-mcp`; the locally installed plugin is `~/.config/opencode/plugins/knowledgetrees.js` (the config's plugin array can be empty). Do not use `--pure`, which disables plugins.

**Launch and lifetime.** The daemon creates a transient user unit `cointos-agent-<id>` running `python3 -m cointos.agents DIR`, with `KillMode=control-group`. That unit prepares the task worktree and runs:
1. `opencode serve --hostname 127.0.0.1 --port 0 --mdns=false` in the worktree.
2. `opencode run --attach URL --dir WORKTREE --format json --auto --title TITLE --model cointos/MODEL`, with the prompt on stdin. Positional prompts containing spaces were previously observed to acquire literal quotes.
3. A resumed task adds `--session SESSION_ID` and a continuation prompt. A daemon restart instead adopts the still-running unit; it does not launch a new task run.

The daemon follows `server.json`, `events.jsonl` and `exit.json`. Events include session IDs and step completions. On prior observed provider 5xx failures OpenCode retried identical requests with backoff, so identical requests alone do not prove a model loop.

**Logs and watching.** Run files include server output, client errors and JSON events under `state/agents/<id>/`; OpenCode's own provider log is `~/.local/share/opencode/log/opencode.log`. `cointos watch [AGENT]` reads the live agent URL/session from the daemon ledger and invokes `opencode attach`. `cointos view --all` enables pop-up viewers, up to the configured limit; `--off` stops opening new ones. Existing idle viewer windows are reused for new agents.

The run's PATH prepends this checkout's `bin/` and `~/.local/bin`; ripgrep is available there.
