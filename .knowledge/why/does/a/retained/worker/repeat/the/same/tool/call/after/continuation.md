---
status: green
revised_at: "2026-09-17T19:58:49+10:00"
---

`ReserveConstantReader` was given a one-file, three-value, read-only task. Its executor JSONL showed repeated completed `read` calls for the identical file, each followed by `step_finish: tool-calls`, an empty text event, and a new step. The wrapper then treated each attached-client tool-call finish as incomplete and submitted a continuation prompt in the exact retained session.

Live OpenCode session inspection established the cause. After each assistant message ending in `tool-calls`, the OpenCode server independently created another assistant message containing the actual textual report and `step-finish: stop`. The attached CLI had already exited and did not forward that later server-side message to executor stdout. Before observing the server-side stop, the wrapper injected a new user continuation; this restarted the task and caused another identical read. The session contained multiple alternating tool-call messages and complete stop messages, including the correct three-value answer.

The installed wrapper now keeps the loopback server alive after attached-client exit, observes the retained session, and mirrors unseen server-side terminal parts into durable executor JSONL instead of injecting another user prompt. Scheduler interruption can terminate this wait and resume the exact session later.

Live qualification passed with Qwen3.8 job `task-7beb8f3fe0cbb26f`, session `ses_f51356ee2ffe53yGyo8pZAQ51L`. The durable log contains exactly one `read` tool call, one `step_finish: tool-calls`, one `worker_server_continuation_wait`, the requested textual answer `107374182400` plus the no-files-changed sentence, and one mirrored `step_finish: stop`. The job terminalized `completed` without a continuation prompt or repeated tool call.
