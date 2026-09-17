---
status: "unverified"
updated_at: "2026-09-17T15:13:51+10:00"
source: "task-b6691b91f4bf0ea0 OpenCode session /message API and executor JSONL 2026-09-17"
---

`ReserveConstantReader` was given a one-file, three-value, read-only task. Its executor JSONL showed repeated completed `read` calls for the identical file, each followed by `step_finish: tool-calls`, an empty text event, and a new step. The installed wrapper treated each tool-call finish as incomplete and immediately submitted a continuation prompt in the exact retained session.

Live OpenCode session inspection established the cause. After each assistant message ending in `tool-calls`, the OpenCode server independently created another assistant message containing the actual textual report and `step-finish: stop`. The attached CLI had already exited and did not forward that later server-side message to executor stdout. Before observing the server-side stop, the wrapper injected a new user continuation; this restarted the task and caused another identical read. The session contained multiple alternating tool-call messages and complete stop messages, including the correct three-value answer.

The wrapper must not interpret attached-client exit after `tool-calls` as a need to add a user prompt. It should keep the loopback server alive, observe the retained session until server-side orchestration reaches a terminal finish, mirror the unseen terminal parts into durable executor JSONL, and only create a continuation prompt when recovery evidence proves the server cannot continue. Scheduler interruption can still terminate this wait and resume the exact session later.