---
status: green
revised_at: "2026-10-14T16:43:15+11:00"
---

Use `cointos agents` to identify a live steward and its exact task, then `cointos task PROJECT:NAME` for its assignment, queue link and receipt. Use `jobs --all` only for historical investigations; archive dumps add unnecessary model prompt tails.

The run directory is `~/.CointOS/state/agents/<agent-id>/`: `run.json` owns task/launch identity, `events.jsonl` streamed OpenCode events, and `server.json` the live child server PID. Its environment must contain `COINTOS_TASK_ID=<exact system task id>` so proposals are attributed and restricted. Inspect launch failures with `journalctl --user -u cointos-agent-<agent-id>.service`.

Check native unit identity and current thoughts/events. Activity timestamps or process existence alone do not prove useful work. `cointos check` covers mechanical invariants, not planning quality.

A steward reads the whole remaining project plan. Accepted steps leave that plan immediately; their current facts belong in focused owners. An approved next step without queued, running or review work is a stalled frontier even when the runtime is green. The steward checks one typed command proposal with `cointos_check_work` and queues it for the manager using a summary and structured dependencies. It does not implement product work. Verify that the command advances remaining approved work rather than re-reviewing a completed stage or declaring completion from an empty queue.
