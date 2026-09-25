---
status: green
revised_at: "2026-09-26T06:25:00+10:00"
---

`ecosystem.dispatch.actionable_jobs(root)` reads `state/jobs/*.json`, skips unreadable or malformed JSON, and returns dictionary records whose `kind` is `agent-task`, whose state is `queued`, `ready`, `claimed`, `runner_starting`, or `running`, and which `resource_control.job_admitted_in_current_mode` admits. It does not require a current route. The profile scheduler uses this list as demand input; its model-specific policy distinguishes pre-admission `claimed` from physically bound `runner_starting`/`running`. Source evidence: `ecosystem/dispatch.py` and `ecosystem/backend_profile_scheduler.py`. Recheck when the dispatch state filter or resource-mode admission changes.
