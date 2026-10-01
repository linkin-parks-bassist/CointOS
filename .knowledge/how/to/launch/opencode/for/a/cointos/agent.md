---
status: green
revised_at: "2026-10-02T01:40:58+10:00"
---

Agents are OpenCode sessions whose only model provider is the CointOS gateway. The on-disk CLI is `~/.local/bin/opencode` 1.18.34; already-running servers may retain their launch version. `cointos/opencode.py` owns per-run configuration, transient units, server/client supervision and event following; `runs.py` owns launch/adoption; `prompts.py` owns the launch message.

## Per-run configuration

Each run gets a mode-0600 `state/agents/<id>/opencode.json` containing its gateway key and:

- provider `cointos` at the local `/v1` endpoint, using `@ai-sdk/openai-compatible`;
- no OpenCode request/header/chunk timeout, because lane waits and prefill can legitimately be long and daemon lifecycle rules own stalls;
- the configured per-lane context limit and whole-reply `max_thought_tokens`;
- knowledgetrees MCP enabled and other global MCP servers disabled;
- sharing and autoupdate disabled;
- broad work permission with web access, privilege/package management, systemd, Git push, lifecycle controls and secrets denied unless the task carries an explicit ability that lifts the relevant CointOS denial;
- read, edit and external-directory denial for every directory listed in the machine-local, untracked `~/.config/cointos/private-paths` (one per line, `#` comments, `~` expanded; absent means none). No ability lifts it, and the source never names those directories;
- edit-tool denial for protected test/harness paths on implementation work. Bash remains same-user capability; the landing gate, not OpenCode permission, enforces commit policy.

Task reasoning effort is daemon metadata. The gateway pins it when rendering and enforces per-reply reasoning caps of 256/384/1,024 tokens for low/medium/xhigh, closing the think block on the same token history before answer/tool generation. Test-contract workers and managers default medium; all others default low unless overridden. A changed effort applies to the next reply, not an already rendered thought.

## Stable task prefix

OpenCode regenerates volatile early system/developer content. On a managed task's first gateway request, `gateway.stable_environment` normalizes and stores the complete system/developer sequence once under its SHA-256 digest; the task stores only that digest. Later requests substitute the pinned sequence before template rendering. Coin and user clients are unchanged. The event journal retains digest/component metadata, never prompt text. This makes warm reuse depend on actual conversation tokens rather than changing startup decoration.

For a fresh managed launch, `prompts.shared_launch_prefix` identifies the semantic end of task-independent role guidance. The gateway renders both the full request and that prefix-only variant through the same backend, takes their exact common token prefix, and gives that boundary to the lane. The lane saves it as a shared snapshot while reading even without a concurrent peer. Later sequential tasks of the same role reuse it only through the ordinary model-and-token-digest match. Continuations and review turns do not perform the extra prefix render.

## Process and session lifetime

A run is a transient `cointos-agent-<id>.service` with its own worktree, memory cap, process group and `COINTOS_AGENT`; its client environment also carries `COINTOS_TASK_ID` and prepends the installed CLI paths. The unit is ordered before cointosd on shutdown so the daemon can persist/requeue work before agents disappear.

The unit starts a private loopback `opencode serve`, then `opencode run --attach URL --dir WORKTREE --format json --auto --title TITLE --model cointos/MODEL`. New runs receive the complete role/assignment/budget message on stdin. Resumed tasks add `--session SESSION_ID`.

The verified 1.18.33 interface rejects an empty noninteractive resumed invocation; empty-resume behavior has not been rechecked on the current 1.18.34 CLI. For an interruption under three hours CointOS supplies the real user turn `Continue.`; after a longer gap it supplies one concise reorientation plus budget notice. OpenCode persists `Continue.` in session context; agents normally treat it as a seamless imperative. Adoption of an already-running unit launches no client and injects no message.

A run becomes assignment-engaged only when its first thought is admitted. Exit before that point is a separately bounded launch failure and refunds the task attempt. After engagement, execution facts from `server.json`, `events.jsonl` and `exit.json` go to the lifecycle reducer; only a validated completion receipt decides task outcome.

## Failure and recovery boundary

A retryable rejection before streaming may be retried by OpenCode. A stream cut after partial content is not a safe continuation primitive: partial assistant state may be recorded and an unfinished thought may no longer render. CointOS therefore preserves committed conversation/checkpoint state and lets its bounded run lifecycle retry or recover; it does not treat transport finish markers or partial text as completion.

Generation time and generated tokens spend the task's run budget; prefill, lane wait and tools do not. Ordinary interruption keeps the same session. Budget exhaustion may start a bounded fresh session with branch/files plus a compact packet of outward text, completed tool evidence, Git state and counters; hidden reasoning is excluded. Worker items without a branch artifact at the earlier checkpoint recover before the full ceiling. Task budget overrides need no restart; changing configured defaults or reasoning budgets needs a compatible daemon replacement, not a model reload.

## Inspection

Run files live under `~/.CointOS/state/agents/<id>/`; OpenCode's provider log is `~/.local/share/opencode/log/opencode.log`. Use `cointos agents`, `cointos watch [AGENT]`, `cointos view --all|--off`, and `journalctl --user -u cointos-agent-<id>.service`. `cointos watch` and `cointos view N` are live terminal views that never return; they refuse to run unless stdin and stdout are terminals, so an agent's captured shell gets a pointer to `agents`/`jobs`/`task` instead of an endless stream of escape codes. The daemon's bounded `state/events.jsonl` records lifecycle/gate/snapshot events without prompts.

OpenCode V2 remains deferred. Before replacing V1, an isolated exercise must preserve one supervised server/client unit per agent and prove plugin/MCP access, permissions, launch/attach, event parsing, delayed-first-byte handling, retry/stream-failure behavior and same-session resume. The GPU scheduler and Coin do not require redesign merely because the harness version changes.
