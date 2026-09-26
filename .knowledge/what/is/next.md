---
status: green
revised_at: "2026-09-27T08:08:55+10:00"
---

The two-hour soak passed its check, agent-count and delivery criteria (06:07–08:07 on 2026-09-27; see `what/is/the/state.md`). Keep sandbox-only scope. What remains needs David's presence or decision.

1. Kill recovery: SIGKILL an agent unit mid-run and time its task's resumption (under 30 s) with checks green afterwards. The harness refused this overnight; David runs it or authorizes it.
2. Coin under load: ten Telegram messages spread across a multi-agent run, each answered visibly within 15 s. This needs David's messages or explicit authorization to send test messages.
3. Workstation: David uses the desktop and one of his own local OpenCode sessions during a multi-agent run; confirm no sluggishness and that his session is served ahead of background agents. Then `cointos halt` mid-run (no CointOS process or model left) and `cointos up` (the interrupted tasks resume).
4. David decides: the `roles/worker.md` step reorder (status committed with the work, then land); the kt front-matter fix on `~/Projects/knowledgetrees` branch `fix/one-status-form` (install only after his go); whether to disable llama-server's own RAM prompt cache (`--cache-ram 0`, relaunches models); whether HTTP/process plumbing timeouts move to config; whether role wording should tell agents to compute with code rather than by hand.
5. Open design gap: a daemon restart during generation can end an agent's turn (OpenCode records the cut stream as a finished step). Design how the gateway ends in-flight streams on stop so that OpenCode retries, and test it against OpenCode.
6. A reboot test if claiming shutdown snapshot persistence. After acceptance, David decides which real projects to add. Sole Survivor is off the current roadmap; catastrophic repair is David's remote intervention.
