---
status: "unresolved"
created_at: "2026-09-15T23:19:12+10:00"
scope: "local"
source: "2026-09-15 ps/proc/pstree inspection; ecosystem/operator_inference.py; tests/test_operator_inference.py; later 794-test passing worker journal"
checked_at: "2026-09-15T23:19:12+10:00"
blocker: "Exact retry branch and initiating tool call were lost when abandoned pipe consumers disappeared."
next_check: "On recurrence, preserve the process, trace sleeps/syscalls, and inspect the temporary job waiting_reason before cleanup."
---


On 2026-09-15 two duplicate commands, PIDs 2179725 and 2180132, were found after roughly 94 minutes running `python3 -m unittest discover -s tests -p test_operator_inference.py -q`. Both were single-threaded, had no children, slept in `hrtimer_nanosleep`, and had accumulated about 200,000 voluntary context switches. Their stdout and stderr were pipes whose launching tool calls were no longer being observed. They were stale verification processes, not CointOS workers or services, and were terminated by process group; no matching test process remained afterward.

`ecosystem.operator_inference.run` contains intentional unbounded wait/retry loops with short sleeps for capacity refresh, route admission, deferred launch, runner observation and cleanup. `tests/test_operator_inference.py` normally injects a sleeper and fixtures that cause these conditions to resolve. A later full discovery ran the same test file as part of 794 passing tests in 61.459 seconds, so the current checked-out code does not reproduce the hang.

The exact wait branch and initiating tool call cannot be recovered after termination because the commands had no log consumer and no per-test progress output. The likely condition is that verification began while shared source/state was changing and entered a retry whose fixture no longer matched the live implementation. This is an inference, not a proven cause.

Next check: if this recurs, preserve the process before killing it, attach `strace -p PID -f -e trace=clock_nanosleep,read,write` or run the individual tests with verbose output, inspect the temporary job's `waiting_reason`, and identify the exact retry branch. Verification launchers should supervise and reap their commands so an interrupted coordinator call cannot leave a childless retry loop indefinitely.
