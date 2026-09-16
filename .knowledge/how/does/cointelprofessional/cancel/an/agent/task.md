---
status: "unverified"
created_at: "2026-09-16T15:49:03+10:00"
updated_at: "2026-09-16T17:02:29+10:00"
scope: "project local"
source: "installed end-to-end cancellation qualification 2026-09-16"
checked_at: "2026-09-16T16:09:00+10:00"
---

Cointelprofessional exposes `cancel_task` with an optional exact `agent_name`. The tool is idempotent through the control-turn action ledger and calls `cli.request_task_cancellation` using the authenticated `telegram:USER_ID` source, so it cannot select another caller's task. With no name it selects the most recently updated active caller task.

The durable CLI transition runs under the task-enqueue lock. Queued, ready, and awaiting-verification work becomes terminal `cancelled` immediately. Running work retains its state and gains `cancellation_requested_at` plus an authenticated-contact reason. It returns the agent name and outcome without exposing an internal job ID. Direct checks covered latest-running selection, named queued cancellation, missing-name behavior, cross-caller isolation, terminal state, and audit emission.

The executor checks the durable cancellation marker before capacity and priority preemption on every preemptible loop. Its cached-job persistence adopts the marker so a concurrent cancellation cannot be erased. A running cancellation uses the existing `before_stop` boundary: cancel the inference request, stop the process group, close the runner and its worker/inference resources, then write terminal `cancelled` state without incrementing preemption count or queuing continuation. If the runner exits naturally in the race window, the post-close path still records terminal cancellation. A retained OpenCode session may remain recorded as recovery evidence but is not resumed.

Source qualification passes: 85 existing control/executor/usage/compaction checks, direct durable cancellation selection and observation checks, direct control-tool routing, `py_compile`, and `git diff --check`. One existing fast-front expectation was updated from the retired 96-token cap to the installed 512-token policy; no new regression test was added. Installed live cancellation remains the next check.

Installed qualification reached a real running Qwen3.8 task with worker lease `lease-2-bc82e024f3c198914e33` and inference lease `inference-456-6b965857a7d97c2d967e`. The authenticated cancellation request was durably accepted. Immediate close could not yet prove backend termination after interrupting the active request, so it correctly entered `reconciliation_required` rather than falsely releasing capacity. A later `recover_abandoned_jobs()` call observed the ended process/idle backend, revoked the proxy credential, released inference, and quiesced the worker. However, `close_runner_round` classified the reaped return code 130 as failed before recovery reapplied user-cancellation intent. The remaining repair is to make successful abandoned-runner reconciliation terminalize a job with a durable cancellation marker as `cancelled`, preserving the cleanup evidence and preventing continuation.

Installed live qualification now passes. A real Telegram-owned Qwen3.8 task reached `running`, accepted a caller-scoped cancellation, interrupted its OpenCode process, and conservatively entered reconciliation because immediate backend termination proof was unavailable. Recovery subsequently proved the ended process and idle backend, revoked the proxy credential, released inference, and quiesced the worker. The recovery path now reapplies durable cancellation intent after generic return-code closure, producing terminal `cancelled`, `logical_run_state: terminal`, `runner_close_state: cancelled`, and no continuation. The qualified resource states were worker `quiescent`, inference `released`, and credential `revoked`.
