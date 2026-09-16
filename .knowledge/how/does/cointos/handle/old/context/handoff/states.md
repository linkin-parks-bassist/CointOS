---
status: "unverified"
created_at: "2026-09-14T22:40:41+10:00"
scope: "local"
source: "Independently inspected current source and design decisions in this turn; isolated real OpenCode read-back and named tests; 2026-09-14"
---

_resume_without_handoff allows ordinary jobs unchanged. For handoff_requested, handoff_durable or continuation_ready, a retained opencode_session is required; if present, context_state becomes running and the original prepared prompt is restored when recorded. execute_next then invokes OpenCode with --session and its normal resume instruction. It neither asks for a handoff nor increments context generation or detaches the session.

Without a retained session, execute_next persists queued plus an explicit recovery-review reason and does not launch. A detached historical context is not recreated from a semantic/mechanical handoff automatically. This keeps the removal from silently discarding conversational state. No live job migration was run. Owner: ecosystem/executor.py _resume_without_handoff/execute_next. Tests: tests/test_opencode_compaction.py legacy retained-session and detached-context cases.
