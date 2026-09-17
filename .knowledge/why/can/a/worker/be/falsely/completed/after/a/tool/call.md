---
status: "unresolved"
created_at: "2026-09-17T14:00:14+10:00"
scope: "local"
source: "scripts/opencode_observable.py; task-4894b791ecbcbafc and task-33f3571db23d4c29 runtime logs and durable state 2026-09-17"
checked_at: "2026-09-17T22:22:00+10:00"
review_when: "Recheck when OpenCode completion reasons, compaction handoffs, acceptance validation, or retained-session launch behavior changes."
blocker: "The source repair is implemented and directly checked but not yet installed or live-qualified through a real incomplete handoff."
next_check: "Install the source repair, run a controlled structured incomplete handoff, and verify the exact OpenCode session continues instead of terminalizing the durable job."
updated_at: "2026-09-18T00:16:33+10:00"
---

`scripts/opencode_observable.py::finish_client()` distinguishes process exit from semantic task completion. An explicit final `step_finish` with reason `stop` is normally the observed successful terminal boundary. A `step_finish` with reason `tool-calls`, `tool_calls`, or `function_call` requires continuation in the exact retained session. An attached OpenCode client can also exit zero without emitting any new `step_finish` after a scheduler interruption; that transport-only exit likewise requires continuation rather than job completion. Explicit error events remain failure and `length` uses the existing length-recovery path.

The first repair handled explicit tool-call reasons but missed the no-new-finish case. `ReserveArithmeticTracer` crossed multiple tool boundaries and scheduler rotations, then its fifth dispatch exited zero without a new semantic finish. The durable job was falsely marked completed while the cumulative transcript still ended at `reason: tool-calls` and contained no final report. Treating a current client with no `step_finish` as continuation successfully reopened the same session; it later emitted a complete report and explicit `step_finish: stop`.

OpenCode then remained alive for post-response housekeeping long enough for fairness to rotate it, causing dispatch 8 after semantic completion. `finish_client()` now breaks on the forwarded explicit `stop`, terminates the attached client, and returns semantic success immediately. That repair is valid for actual final reports and live-qualified server-side continuation.

A remaining false-completion form appeared in builder `task-33f3571db23d4c29`. After extensive preflight and context compaction, the assistant emitted a structured handoff whose own Work State said no code changes had been made, acceptance compilation/checks were still pending, and the Next Move began with applying the edit. The response nevertheless ended with `step_finish: stop`; CointOS marked the durable job completed with exit zero, closed the observable endpoint, and did not validate the task contract's acceptance items. The exact session ID and handoff survive, but there is no checked managed one-call procedure for reopening this terminalized job, so the coordinator completed the small patch locally rather than mutate queue JSON or launch unmanaged inference.

Completion therefore needs more than transport exit and a nominal stop when the final output explicitly declares unfinished acceptance. Recovery must preserve and re-admit the exact retained session. Creation of a fresh worker is not equivalent and must not be the default response.

Read-only mapper `task-940715ef112bf968` located the minimal implementation seam. `finish_client()` already JSON-decodes every streamed part and collects part IDs, but ignores `part["text"]`; on `step_finish` reason `stop` it forces semantic success. `main()` then skips continuation and returns zero. The same `main()` loop already retains the exact session and reattaches it for length recovery, so an explicit incomplete verdict can reuse that loop. `await_server_finish()` needs the same verdict because server-side continuation can also end at nominal stop. The remaining design question is the narrow structured signal: retain the last text part before stop and recognize only an explicit unfinished-work/acceptance declaration, avoiding a broad natural-language parser or false continuation from historical discussion.

Source implementation `task-b3169e8d7267a98d` adds a conservative structured-handoff predicate, retains the last text part in both direct-client and server-finish paths, and routes an incomplete stop into the existing uncapped same-session continuation loop. Direct checks passed for the historical shape, inactive-none, missing numbered Next Move, and ordinary prose; source compilation passes. Installation and live qualification remain pending.
