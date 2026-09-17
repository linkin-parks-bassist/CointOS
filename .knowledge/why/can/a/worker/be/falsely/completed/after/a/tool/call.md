---
status: "unverified"
created_at: "2026-09-17T14:00:14+10:00"
scope: "local"
source: "scripts/opencode_observable.py; task-4894b791ecbcbafc runtime log and recovered durable state 2026-09-17"
checked_at: "2026-09-17T15:06:00+10:00"
review_when: "Recheck when OpenCode JSON completion reasons or retained-session launch behavior changes; live-qualify prompt post-stop exit on the next managed task."
updated_at: "2026-09-17T14:59:15+10:00"
---

`scripts/opencode_observable.py::finish_client()` distinguishes process exit from semantic task completion. An explicit final `step_finish` with reason `stop` is the observed successful terminal boundary. A `step_finish` with reason `tool-calls`, `tool_calls`, or `function_call` requires continuation in the exact retained session. An attached OpenCode client can also exit zero without emitting any new `step_finish` after a scheduler interruption; that transport-only exit likewise requires continuation rather than job completion. Explicit error events remain failure and `length` uses the existing length-recovery path.

The first repair handled explicit tool-call reasons but missed the no-new-finish case. `ReserveArithmeticTracer` crossed multiple tool boundaries and scheduler rotations, then its fifth dispatch exited zero without a new semantic finish. The durable job was falsely marked completed while the cumulative transcript still ended at `reason: tool-calls` and contained no final report. Treating a current client with no `step_finish` as continuation successfully reopened the same session; it later emitted a complete report and explicit `step_finish: stop`.

OpenCode then remained alive for post-response housekeeping long enough for fairness to rotate it, causing dispatch 8 after semantic completion. `finish_client()` now breaks on the forwarded explicit `stop`, terminates the attached client, and returns semantic success immediately. The erroneous post-stop dispatch was terminated and the task recovered to durable completion from its preserved report and stop event. Source compilation, the 108 existing focused checks, and direct stream checks for no-finish continuation, tool-call continuation, and prompt stop termination pass. The installed wrapper contains the fix; the next managed task should live-qualify prompt post-stop process exit.