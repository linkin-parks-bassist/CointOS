---
status: green
revised_at: "2026-09-20T05:13:41+10:00"
---

_resume_without_handoff allows ordinary jobs unchanged. For handoff_requested, handoff_durable or continuation_ready, a retained opencode_session is required; if present, context_state becomes running and the original prepared prompt is restored when recorded. execute_next then invokes OpenCode with --session and its normal resume instruction. It neither asks for a handoff nor increments context generation or detaches the session.

Without a retained session, execute_next persists queued plus an explicit recovery-review reason and does not launch. A detached historical context is not recreated from a semantic/mechanical handoff automatically. This keeps the removal from silently discarding conversational state. No live job migration was run. Owner: ecosystem/executor.py _resume_without_handoff/execute_next. Tests: tests/test_opencode_compaction.py legacy retained-session and detached-context cases.
Live observation on 2026-09-20: supervised KT-owner audit task-73e862421c6f4c4e emitted worker_incomplete_handoff for session ses_f45327bf3ffe7Lst1FiyZmzEnr at log event index 72. The same log then recorded a new step_start and further tool calls under that same session ID; the worker rewrote its assigned leaves and the durable job ended completed with opencode_session unchanged. This is one observed exact-session continuation through an explicit incomplete handoff. It does not establish correctness for detached sessions, every compaction reason, or saturation/recovery scenarios. Next check: review other incomplete-handoff events and qualify detached/restart paths separately.
