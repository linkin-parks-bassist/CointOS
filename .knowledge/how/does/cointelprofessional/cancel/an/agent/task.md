---
status: "unverified"
created_at: "2026-09-16T15:49:03+10:00"
updated_at: "2026-09-16T16:15:12+10:00"
scope: "project local"
source: "source cancellation implementation and direct qualification 2026-09-16"
checked_at: "2026-09-16T16:09:00+10:00"
blocker: "The complete cancellation path is implemented and source-qualified. Installed end-to-end cancellation of a running task has not yet been exercised."
next_check: "Install at an idle boundary, cancel one controlled running Telegram-owned task, and verify normal worker/inference cleanup plus terminal cancelled state without continuation."
---

Cointelprofessional exposes `cancel_task` with an optional exact `agent_name`. The tool is idempotent through the control-turn action ledger and calls `cli.request_task_cancellation` using the authenticated `telegram:USER_ID` source, so it cannot select another caller's task. With no name it selects the most recently updated active caller task.

The durable CLI transition runs under the task-enqueue lock. Queued, ready, and awaiting-verification work becomes terminal `cancelled` immediately. Running work retains its state and gains `cancellation_requested_at` plus an authenticated-contact reason. It returns the agent name and outcome without exposing an internal job ID. Direct checks covered latest-running selection, named queued cancellation, missing-name behavior, cross-caller isolation, terminal state, and audit emission.

The executor checks the durable cancellation marker before capacity and priority preemption on every preemptible loop. Its cached-job persistence adopts the marker so a concurrent cancellation cannot be erased. A running cancellation uses the existing `before_stop` boundary: cancel the inference request, stop the process group, close the runner and its worker/inference resources, then write terminal `cancelled` state without incrementing preemption count or queuing continuation. If the runner exits naturally in the race window, the post-close path still records terminal cancellation. A retained OpenCode session may remain recorded as recovery evidence but is not resumed.

Source qualification passes: 85 existing control/executor/usage/compaction checks, direct durable cancellation selection and observation checks, direct control-tool routing, `py_compile`, and `git diff --check`. One existing fast-front expectation was updated from the retired 96-token cap to the installed 512-token policy; no new regression test was added. Installed live cancellation remains the next check.