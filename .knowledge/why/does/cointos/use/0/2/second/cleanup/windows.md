---
status: "unverified"
created_at: "2026-09-16T05:46:49+10:00"
scope: "local"
source: "observable Qwen implementation; coordinator inspection; 42 executor and 8 time-policy checks 2026-09-16"
updated_at: "2026-09-16T06:51:33+10:00"
---

CointOS no longer uses an implicit 0.2-second default for owned executor-process cleanup. `config/time.cfg` defines `executor.cleanup_deadline_seconds = 10`; `survival/time_policy.py` requires the key; and `ecosystem.executor._cleanup_deadline_seconds()` resolves it through the shared policy owner. Launch-failure cleanup, `gated_child_cleanup`, and `_stop_recovered_runner` use that deadline when callers omit a timeout. Explicit caller-supplied timeouts remain supported for narrow probes and specialized operations.

The observable Qwen worker exited cleanly. Coordinator checks passed: `py_compile` for executor and time-policy code, all 42 existing executor checks, and all 8 existing time-policy checks. The existing in-memory policy fixture was extended with the new required production key; no new regression test was authored.