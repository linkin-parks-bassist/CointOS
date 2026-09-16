---
status: "unverified"
scope: "CointOS project"
review_when: Recheck when OpenCode changes run positional or stdin input behavior.
updated_at: "2026-09-16T17:02:29+10:00"
source: "installed executor prompt qualification 2026-09-16"
---

OpenCode 1.18.31's `run [message..]` implementation deliberately wraps every positional argument containing a space in literal double quotes before sending it as the text part. This is OpenCode argument rendering, not shell display. The same implementation reads non-TTY stdin and uses piped text verbatim when no positional message is supplied.

`scripts/opencode_observable.py` therefore removes the canonical single prompt from the attached client's positional argv, opens the client's stdin pipe, writes the exact prompt bytes and closes the pipe. Quotes never enter the session, multiline formatting is retained, and no busy-session PATCH race is needed. The earlier post-launch PATCH workaround was removed after live evidence showed OpenCode rejects part edits while the session is busy, leaving the trailing quote visible during work. The current already-running worker was repaired after it became editable; future launches use stdin from the start.

The two existing observable process checks and py_compile pass after the stdin change. Next direct live worker launch should confirm the initial stored text has neither outer quote while still busy; existing checks do not prove that live presentation boundary.

Installed executor qualification on 2026-09-16 exposed a caller that violated this wrapper contract. `executor.execute_next` passed the prepared prompt only as the observable wrapper's stdin and built the wrapped OpenCode command without a positional message. The wrapper intentionally ignores its own stdin, found no `command[2]`, and therefore piped an empty prompt to OpenCode; 1.18.31 exited with `You must provide a message or a command`. Worker and inference resources closed cleanly. Source now inserts the selected initial or resume prompt text at command position 2 immediately before observable wrapping. The wrapper then removes that positional argument and pipes the exact bytes to its client as designed, retaining the no-quote behavior. Fifty-four existing executor/compaction/usage checks and py_compile pass; installed live qualification remains next.

Installed qualification now confirms the executor-supplied positional prompt crossed the observable wrapper correctly: OpenCode created a retained session and the task reached running inference instead of exiting with the empty-message error. The wrapper continues to remove the positional argument and pipe its exact bytes, so the quote workaround and prompt delivery remain one mechanism.
