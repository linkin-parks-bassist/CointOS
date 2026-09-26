---
status: green
revised_at: "2026-09-27T04:16:50+10:00"
---

Four workers on two lanes, main-branch settlement and the turn-slice fix are live (see `what/is/the/state.md`). Keep sandbox-only scope.

1. Let the running multi-agent batch finish, and confirm live that `no agent starves` stays green with the turn-slice fix and that every item settles `done on main` with nothing stranded. Keep the queue fed so at least four agents stay live, which lets the same run count toward the unattended hour and two-hour soak.
2. Kill recovery: SIGKILL an agent unit mid-run and time its task's resumption (under 30 s) with checks green afterwards. The harness refused this overnight; David runs it or authorizes it.
3. David reviews: the `roles/worker.md` step reorder (status committed with the work, then land), and the kt front-matter fix on `~/Projects/knowledgetrees` branch `fix/one-status-form` (install only after his go). Decide whether HTTP/process plumbing timeouts move to config.
4. Demonstrate Coin's real Telegram round trip and ten-message response timing under load; this needs David's messages or explicit authorization to send test messages.
5. Workstation responsiveness and user-class priority under load, halt/up mid-soak, and a reboot test if claiming shutdown snapshot persistence.
6. After acceptance, David decides which real projects to add. Sole Survivor is off the current roadmap; catastrophic repair is David's remote intervention.
