---
status: green
revised_at: "2026-09-27T05:56:04+10:00"
---

Four agents on two lanes with main-branch settlement, turn slices, bounded steps, agent memory caps and thought-end activity are live (see `what/is/the/state.md`). Keep sandbox-only scope.

1. Start a clean two-hour soak from the latest deploy: keep at least four agents live (queue enough sandbox items; avoid briefs whose tests can explode, like digits inside RLE text), sample checks every 5 s, and record whether `no agent starves` and `memory within bounds` stay green. Confirm live that `lane state lost` events, if any, recover without starving equals.
2. Kill recovery: SIGKILL an agent unit mid-run and time its task's resumption (under 30 s) with checks green afterwards. The harness refused this overnight; David runs it or authorizes it.
3. David decides: the `roles/worker.md` step reorder (status committed with the work, then land); the kt front-matter fix on `~/Projects/knowledgetrees` branch `fix/one-status-form` (install only after his go); whether to disable llama-server's own RAM prompt cache (`--cache-ram 0`, relaunches models); whether HTTP/process plumbing timeouts move to config; whether role wording should tell agents to compute with code rather than by hand.
4. Demonstrate Coin's real Telegram round trip and ten-message response timing under load; this needs David's messages or explicit authorization to send test messages.
5. Workstation responsiveness and user-class priority under load, halt/up mid-soak, and a reboot test if claiming shutdown snapshot persistence.
6. After acceptance, David decides which real projects to add. Sole Survivor is off the current roadmap; catastrophic repair is David's remote intervention.
