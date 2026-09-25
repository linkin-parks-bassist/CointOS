---
status: green
revised_at: "2026-09-26T02:20:51+10:00"
---

A managed job can be `queued`, `ready`, `claimed` or `runner_starting` before OpenCode creates `logs/runs/TASK.opencode.log`. Installed `scripts/worker-log-summary TASK` shows the durable job state and `events=0 (worker log not created yet)` for that expected condition instead of throwing `FileNotFoundError`. If a running or terminal job lacks its log, it exits with an explicit error rather than misrepresenting absence as normal prelaunch. The failure was observed on a legitimately queued CointOS-only growth probe. After deployment, the installed command produced the expected queued/no-log output against an isolated temporary job record and returned 0; the temporary record was removed. Source compilation and an existing-log smoke also passed.
