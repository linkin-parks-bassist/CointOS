---
status: green
revised_at: "2026-09-16T15:47:47+10:00"
checked_at: '2026-09-16T15:46:00+10:00'
---

Cointelprofessional exposes `inspect_task_progress` for a direct durable progress query. The tool accepts an optional exact `agent_name`; its runtime only considers agent-task records whose source is the authenticated contact's `telegram:USER_ID`. With no name it selects the most recently updated active record in queued, ready, running, or awaiting_verification state, falling back to the caller's most recently updated submitted task. No match returns a truthful `found: false` result.

A found result projects lifecycle fields useful to the deep controller: agent name, state, task, role, model, update time, attempts, logical-run state, runner phase, preemption reason, and failure reason when present. When the selected record names an output path, the runtime resolves it beneath `cli.ROOT` and, only for a regular file inside that root, reports its byte size and UTC modification time. It does not read or return worker output content, mutate the task, or expose another caller's jobs.

The implementation is in `ecosystem/control_agent.py` and `ecosystem/control_runtime.py`. Direct injected checks covered active preference over a newer completed task, exact named selection, cross-caller exclusion, no-match behavior, safe output metadata, and absence of output content. Both files compile and `git diff --check` passes. Installed control-worker adoption remains to be observed.