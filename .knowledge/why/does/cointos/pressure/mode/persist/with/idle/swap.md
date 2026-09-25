---
status: green
revised_at: "2026-09-20T19:17:31+10:00"
---

`ecosystem/resource_control.py:_threshold_state` treats absolute `swap_used_gb` above `config/resource-policy.json` pressure maximum (1.0 GiB) as pressure. The pressure release path at `resource_control.py:1828-1868` requires a sustained healthy threshold before it reopens the work gate and resumes interrupted jobs. On 2026-09-20, installed `state/resource-control.json` stayed in pressure mode with 1.424 GiB swap, approximately 58 GiB MemAvailable, 41.95 GiB GTT, zero full PSI and no OOM kills; `task-6796206bc4b64292` remained interrupted and resumable. A `vmstat 1 5` probe showed zero swap-in and swap-out on its four interval samples while used swap stayed flat. This demonstrates that occupied swap can keep dispatch gated after the observed swapping activity has stopped. The earlier client-stop verification error reflects a check while `agent-ecosystem.service` was still activating; later systemd state was inactive. An attempted non-interactive sudo capability check reported that a password is required, so no swap clearing or privileged recovery was attempted.

Blocker: The live absolute swap occupancy remains above the configured pressure threshold; whether the threshold policy should use occupancy, activity, or another sustained signal has not been reviewed against desktop safety. Non-interactive privileged swap clearing is unavailable.

Next check: Review pressure policy and live swap/PSI trends before changing thresholds or recovery behavior. Let the normal release path resume the existing task if the gate becomes healthy; do not bypass it merely to run a worker.
