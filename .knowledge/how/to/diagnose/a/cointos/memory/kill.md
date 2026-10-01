---
status: green
revised_at: "2026-10-02T02:16:12+10:00"
---

Find the kernel's OOM constraint, exact victim PID and memory cgroup before treating a desktop memory notification as machine-wide exhaustion. A unit under `app.slice` can hit its own cap while the desktop and model service still have memory.

Use a bounded time window around the report. `journalctl -k` selects the current boot by default; for an older incident use `journalctl --list-boots` and select its boot, or search retained boots with:

```bash
journalctl _TRANSPORT=kernel --since 'START' --until 'END' --no-pager \
  --grep='oom-kill|Out of memory|Killed process|Memory cgroup out of memory'
```

Read the full matching incident. `CONSTRAINT_MEMCG` with `oom_memcg` and `task_memcg` naming an agent or test unit identifies a cgroup-local kill; it does not establish host-wide exhaustion. Match the PID and unit with `journalctl --user -u EXACT.service` in the same window. A deliberate transient landing/memory test and a genuine agent consuming its cap are different cases. Compare the unit command with the installed runtime: legacy source-state units are not evidence about a current OpenCode run.

For a current agent, inspect its exact task/session and recovery through `cointos agents`, `jobs --all`, the run directory and daemon journal. Use current ledger headroom/PSI and `/proc/meminfo` for current pressure; old kernel events do not prove present pressure. Missing retained logs do not prove that no kill happened. Diagnose the tool/allocation and recovery behavior rather than removing protective caps to silence the notification.

Agent units and isolated landing checks have their own configured memory limits; Lemonade runs separately in `inference.slice`. `what/are/the/machine/facts.md` owns the memory pool and measurements. `what/is/the/live/acceptance/evidence/for/cointos.md` owns inspected incidents and their evidence boundary. Provenance: retained kernel/systemd journals, `runs.py`, `landing.py`, memory configuration and the lifecycle reducer.
