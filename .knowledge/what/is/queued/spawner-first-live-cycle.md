---
status: green
revised_at: "2026-09-26T09:51:22+10:00"
---

Status: queued

Observe one complete autonomous spawner cycle on the installed runtime and record the evidence.

**Start only when** `what/is/queued/autonomy-changes-tests-and-commit.md` is `Status: done`; otherwise set this item `Status: blocked` and stop.

**Known.** `ecosystem/spawner.py` is implemented and enabled: one-minute `agent-spawner.timer`, at most one spawn per tick, up to two agents, picking `urgent/` then `queued/` items (worker), `drafted/` ideas (manager), then a manager survey, then a steward card. No spawner-initiated cycle has been observed yet.

**Outcome.** Evidence that the loop closed itself: a job whose source starts `spawner:` was created, ran in the project workspace, updated its leaf (or completed a survey or steward card) and exited cleanly, with leases closed and no dangling jobs.

**How to tell it is done.** This brief records the job id, the leaf touched, the job's final state and a `cointos-health --json` reading, then sets `Status: done`. If the cycle is still absent after a reasonable wait, record what blocks it (audit trail, job states) and set `Status: blocked` with the next check.
