---
status: green
revised_at: "2026-09-14T22:45:44+10:00"
---

Runner stdout is a mixed stream, not a guaranteed stream of JSON event objects. `opencode_session_id` ignores malformed JSON and valid JSON values that are not dictionaries before looking for a string `sessionID` beginning with `ses_`. It returns the first qualifying event identifier; unreadable output returns no identifier.

Persisting the retained session before runner cleanup exposed the old assumption: numeric stdout parsed successfully, then `.get` raised, preventing the cleanup/reconciliation path from completing. Skipping non-object JSON keeps session discovery best-effort and allows cleanup to proceed. The regression covers numbers, null, arrays, strings, ordinary text and a subsequent valid session event. This changes parsing robustness, not session identity or resume semantics.
