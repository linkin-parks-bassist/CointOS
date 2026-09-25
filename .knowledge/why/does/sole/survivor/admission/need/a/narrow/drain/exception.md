---
status: green
revised_at: "2026-09-26T02:34:14+10:00"
---

Emergency resource control closes the workload gate to `draining` before it stops ordinary clients, then prepares and dispatches a Sole Survivor repair job. Without an exception, `workload_control.acquire_worker` defers that job with `drain`; if acquisition is exempted but inference reservation is not, `inference_capacity._validate_worker_lease` rejects it with `worker admission is closed`. The executor returns the job to ready and the active emergency can lose its verified live lane.

The installed exception is limited to a resource-control-owned draining gate, a resource state in `emergency` phase `survivor_ready` or `active`, and the exact `sole_survivor_job` recorded by that incident. It also checks the durable job's emergency source, authority, role, model, and owner against the request. Worker acquisition and inference reservation use the same predicate. Ordinary jobs and other drain owners stay closed. During incident `20260925T162248Z-0`, after deployment, Sole Survivor `task-226302defd1b67a6` reached `running` with live worker and inference leases, and the resource guard cleared `emergency_error`.
