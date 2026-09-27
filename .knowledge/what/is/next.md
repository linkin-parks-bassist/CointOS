---
status: green
revised_at: "2026-09-27T10:15:34+10:00"
---

The two-hour soak passed its check, agent-count and delivery criteria (06:07–08:07 on 2026-09-27; see `what/is/the/state.md`). Keep sandbox-only scope for project work. What remains needs David's presence or decision.

1. Kill recovery: SIGKILL an agent unit mid-run and time its task's resumption (under 30 s) with checks green afterwards. The harness refused this overnight; David runs it or authorizes it.
2. Coin under load: ten Telegram messages spread across a multi-agent run, each answered visibly within 15 s. This needs David's messages or explicit authorization to send test messages.
3. Workstation: David uses the desktop and one of his own local OpenCode sessions during a multi-agent run; confirm no sluggishness and that his session is served ahead of background agents. Then `cointos halt` mid-run (no CointOS process or model left) and `cointos up` (the interrupted tasks resume).
4. Gardener, deployed 2026-09-27 (`7507533`) for the CointOS and sandbox trees: confirm its first routine passes land and settle as done, and that a brown or yellow leaf starts a gardener ahead of queued work.
5. David's answers of 2026-09-27 still to do: tell agents to compute with code rather than by hand. Discussion pending: workers should not merge their own work; another agent should review it independently and then merge (a reviewer role); a reshape rung for the ladder, and whether to fork llama.cpp for control of its memory handling; closing agents' network access except for fetching (David's request, under discussion).
6. Open design gap: a daemon restart during generation can end an agent's turn (OpenCode records the cut stream as a finished step). Design how the gateway ends in-flight streams on stop so that OpenCode retries, and test it against OpenCode.
7. A reboot test if claiming shutdown snapshot persistence. After acceptance, David decides which real projects to add. Sole Survivor is off the current roadmap; catastrophic repair is David's remote intervention.
