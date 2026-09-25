---
status: green
revised_at: "2026-09-16T05:46:27+10:00"
---

When an emergency reached `model_loaded` but Sole Survivor preparation failed before `sole_survivor_job` was recorded, `resource-control recover` now accepts the empty job identity as an explicit local operator recovery. It labels the actor `operator:failed-survivor-recovery` and retains the normal live resource-health check, interrupted-lease reconciliation, work-gate smoke transition, and service-start verification. If a survivor job exists, the exact `AGENT_JOB_ID` requirement remains. Other missing-survivor states remain refused.

This repaired incident `20260915T111547Z-0`, whose survivor descriptor was non-canonical. All 57 existing resource-control checks passed, the installed recovery returned `ok: true`, and the work gate reopened.