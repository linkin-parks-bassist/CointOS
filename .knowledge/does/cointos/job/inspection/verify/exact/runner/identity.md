---
status: green
revised_at: "2026-09-25T22:38:28+10:00"
verifiable: "true"
---

Yes. For a managed job, the inspector reads `executor_pid` and `executor_start_ticks`. It reports `alive` only when the current process start ticks match the durable value; a mismatched value reports `pid_reused`.

Proof:

```bash
python3 - <<'PY'
import os
from ecosystem.executor import process_identity
from ecosystem.job_inspection import runner_observation
identity = process_identity(os.getpid())
job = {"executor_pid": identity["pid"],
       "executor_start_ticks": identity["start_ticks"]}
assert runner_observation(job)["state"] == "alive"
job["executor_start_ticks"] += 1
assert runner_observation(job)["state"] == "pid_reused"
PY
```
