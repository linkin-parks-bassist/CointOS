---
status: green
revised_at: "2026-10-17T16:26:08+11:00"
---

Distinguish CointOS's protective guard, kernel OOM, cgroup caps and userspace systemd-oomd before treating a memory notification as host exhaustion. Missing kernel OOM lines do not exclude oomd.

For an agent ending with `memory needed`, inspect installed state/events.jsonl for the matching `Giving memory back` alert. Negative headroom means available memory fell below the desktop reserve or server allowance, not that physical RAM was exhausted. The guard sheds snapshots first and stops background agents uncharged when shortage persists; sustained PSI can also stop them. Recovery requires consecutive calm time (currently 120 seconds), so positive headroom and paused agents can coexist. Compare Coin's stored reply timestamp against the stop and `Memory is calm` events; present healthy measurements cannot establish conditions at the earlier stop. Use daemon.guard, memory.headroom_gb and current memory configuration to interpret the trigger.

Use a bounded incident window. `journalctl -k` defaults to the current boot; use `journalctl --list-boots` and the incident boot, or retained `_TRANSPORT=kernel` journals. Read matching incidents and exact service journals. `CONSTRAINT_MEMCG` with `oom_memcg`/`task_memcg` identifies a cgroup-local victim. Match its PID, command and installed runtime; legacy source-state units and deliberate isolated tests do not establish current OpenCode failures.

For userspace kills, inspect `journalctl -u systemd-oomd.service` and the victim unit in the same window. Its kill line identifies the selected cgroup and trigger. `oomctl` shows monitored cgroups and thresholds; `systemctl show UNIT -p ManagedOOMSwap -p ManagedOOMMemoryPressure -p MemoryHigh -p MemoryMax -p MemoryCurrent -p MemorySwapCurrent` shows policy/accounting. A host swap threshold can kill a monitored inference unit while substantial RAM remains. Distinguish this from hard caps and pressure triggers.

Match task/session and recovery through agents, task inspection, run files and daemon events. Current ledger headroom/PSI and /proc/meminfo describe present pressure. Swap occupancy can persist after distress; sample current swapping and PSI before calling it thrashing. Missing logs prove no absence. Diagnose allocation, kill policy and recovery rather than removing protection to silence notifications. Policy repair must preserve desktop protection and avoid manufactured pressure.

Agent/test units have independent limits; Lemonade belongs to inference.slice. Machine facts own memory pools; live acceptance owns inspected incidents. Evidence: kernel/systemd/oomd journals, live cgroup policy, daemon.py, memory.py, runs.py, landing.py, memory configuration and lifecycle reduction.
