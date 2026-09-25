---
status: green
revised_at: "2026-09-26T00:44:37+10:00"
---

`ecosystem/executor.py:_process_alive` first verifies exact `executor_owner_pid` plus `executor_owner_start_ticks` for current-generation jobs, so a recycled PID cannot impersonate their owner. Older job records lacking both owner fields fall back to `os.kill(executor_pid, 0)` without checking a start tick. If the old PID has been reused by another process, that fallback may report the abandoned legacy job as live and defer its recovery. The installed dynamic claim path writes exact owner identity for new jobs; this risk applies to legacy or malformed records missing it, not the two 2026-09-26 live lane audits.

A safe repair should prefer any stored exact runner start-tick evidence for the legacy fallback and treat identity ambiguity as reconciliation requiring observation, not blindly kill an unrelated PID. Do not replace this with a timeout that discards retained work.
