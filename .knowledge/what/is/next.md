---
status: green
revised_at: "2026-09-27T08:36:27+10:00"
---

The two-hour soak passed its check, agent-count and delivery criteria (06:07–08:07 on 2026-09-27; see `what/is/the/state.md`). Keep sandbox-only scope. What remains needs David's presence or decision.

1. Kill recovery: SIGKILL an agent unit mid-run and time its task's resumption (under 30 s) with checks green afterwards. The harness refused this overnight; David runs it or authorizes it.
2. Coin under load: ten Telegram messages spread across a multi-agent run, each answered visibly within 15 s. This needs David's messages or explicit authorization to send test messages.
3. Workstation: David uses the desktop and one of his own local OpenCode sessions during a multi-agent run; confirm no sluggishness and that his session is served ahead of background agents. Then `cointos halt` mid-run (no CointOS process or model left) and `cointos up` (the interrupted tasks resume).
4. Deploy, with one daemon restart when no agent is mid-thought (item 6's gap): the memory ladder, the finite tool-call cooldown and the move of every plumbing number into config (all committed 2026-09-27 morning, `5cfd7de`, `e065fea`; David decided the config move).
5. David's answers of 2026-09-27: install the kt front-matter fix (`fix/one-status-form`); tell agents to compute with code rather than by hand. Discussion pending: workers should not merge their own work; another agent should review it independently and then merge (a reviewer role, replacing the step reorder in `roles/worker.md`); llama-server's own RAM prompt cache (David asks why it exists; likely to be disabled); a reshape rung for the ladder, and whether to fork llama.cpp for control of its memory handling.
6. Open design gap: a daemon restart during generation can end an agent's turn (OpenCode records the cut stream as a finished step). Design how the gateway ends in-flight streams on stop so that OpenCode retries, and test it against OpenCode.
7. A reboot test if claiming shutdown snapshot persistence. After acceptance, David decides which real projects to add. Sole Survivor is off the current roadmap; catastrophic repair is David's remote intervention.
