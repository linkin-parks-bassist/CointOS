---
status: "unverified"
scope: "CointOS project"
review_when: Recheck when OpenCode changes run positional or stdin input behavior.
updated_at: "2026-09-15T18:43:54+10:00"
source: "Official anomalyco/opencode run.ts positional quoting and stdin behavior; live busy-session PATCH miss; scripts/opencode_observable.py stdin implementation 2026-09-15"
---

OpenCode 1.18.31's `run [message..]` implementation deliberately wraps every positional argument containing a space in literal double quotes before sending it as the text part. This is OpenCode argument rendering, not shell display. The same implementation reads non-TTY stdin and uses piped text verbatim when no positional message is supplied.

`scripts/opencode_observable.py` therefore removes the canonical single prompt from the attached client's positional argv, opens the client's stdin pipe, writes the exact prompt bytes and closes the pipe. Quotes never enter the session, multiline formatting is retained, and no busy-session PATCH race is needed. The earlier post-launch PATCH workaround was removed after live evidence showed OpenCode rejects part edits while the session is busy, leaving the trailing quote visible during work. The current already-running worker was repaired after it became editable; future launches use stdin from the start.

The two existing observable process checks and py_compile pass after the stdin change. Next direct live worker launch should confirm the initial stored text has neither outer quote while still busy; existing checks do not prove that live presentation boundary.
