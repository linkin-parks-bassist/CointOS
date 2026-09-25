---
status: green
revised_at: "2026-09-26T04:12:04+10:00"
checked_at: "2026-09-20T13:16:40+10:00"
---

A nominal OpenCode `step_finish: stop` proves a model turn ended, not that a task's objective was met. `scripts/opencode_observable.py` already continues the exact retained session after tool-call finishes, a zero-exit client with no new semantic finish, and a conservative structured incomplete handoff. It terminates the attached client on an explicit final stop so post-response housekeeping does not create another dispatch. One live same-session structured-handoff continuation succeeded. The parser intentionally does not infer incompletion from arbitrary future-tense prose; that would risk false positives.

`ecosystem/executor.py` now applies `ecosystem.acceptance.artifact_failure` before turning an ordinary `run_finished` job into `completed`. A declared artifact must exist as a nonempty file or the job becomes failed with an acceptance error. This gate rejected both Sole Survivor runs that ended without their required conclusion file. The gate does not validate content truth, and an absent/default acceptance list contributes no deterministic failure. A job that merely says it will do work next can therefore still be falsely completed if it stops nominally and has no explicit evidence contract. Optional verifier paths have their separate transition.

Do not solve this by parsing broad natural-language intent as proof of success. The next safe improvement is to define explicit, task-scoped acceptance evidence for work types that need it, while retaining exact-session continuation for clearly incomplete handoffs. A terminal artifact failure currently fails the job rather than reopening the same session; any retry policy must preserve authority and evidence rather than silently creating a fresh worker.
