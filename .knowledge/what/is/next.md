---
status: green
revised_at: "2026-09-27T11:40:09+10:00"
---

The two-hour soak passed its check, agent-count and delivery criteria (06:07–08:07 on 2026-09-27; see `what/is/the/state.md`). Keep sandbox-only scope for project work. What remains needs David's presence or decision.

0. **First: make every task small** (`what/is/the/shape/of/cointos/work.md`). Current tasks are too large for the local models. Design with David, then build: managers break ideas into pipelined single-concern stages; reviewers report on boundaries and pass up to higher-level coherence reviewers; routine gardeners check 1–3 random leaves and end, with separate broad-scale gardeners watching for tree poisoning. The C JSON parser in the sandbox is its first test; its current manager was given the old, too-large breakdown task.

1. Kill recovery: SIGKILL an agent unit mid-run and time its task's resumption (under 30 s) with checks green afterwards. The harness refused this overnight; David runs it or authorizes it.
2. Coin under load: ten Telegram messages spread across a multi-agent run, each answered visibly within 15 s. This needs David's messages or explicit authorization to send test messages.
3. Workstation: David uses the desktop and one of his own local OpenCode sessions during a multi-agent run; confirm no sluggishness and that his session is served ahead of background agents. Then `cointos halt` mid-run (no CointOS process or model left) and `cointos up` (the interrupted tasks resume).
4. Live checks of what was deployed on 2026-09-27: the gardener (first routine passes land and settle as done; a brown or yellow leaf starts one ahead of queued work) and the integrator (the first items reviewed and landed as one commit each, their leaves gone and their `Landed:` trailers satisfying dependencies; a send-back resumes its worker with the notes). The smoke test is the C JSON parser drafted in the sandbox; David's independent check of it is kept outside the agents' reach.
5. David's answers of 2026-09-27 still to do: tell agents to compute with code rather than by hand. Discussion pending: a CointOS MCP server (land, queue and status as tools); a reshape rung for the ladder, and whether to fork llama.cpp for control of its memory handling; closing agents' network access except for fetching (David's request, under discussion).
6. Open design gap: a daemon restart during generation can end an agent's turn (OpenCode records the cut stream as a finished step). Design how the gateway ends in-flight streams on stop so that OpenCode retries, and test it against OpenCode.
7. A reboot test if claiming shutdown snapshot persistence. After acceptance, David decides which real projects to add. Sole Survivor is off the current roadmap; catastrophic repair is David's remote intervention.
