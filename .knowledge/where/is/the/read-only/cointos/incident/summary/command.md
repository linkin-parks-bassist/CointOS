---
status: green
revised_at: "2026-09-26T04:06:23+10:00"
---

Installed `cointos-incident` is the bounded, read-only incident view on PATH; its source is `scripts/cointos-incident`. Run `cointos-incident [INCIDENT_ID] --json`, omitting the ID for the current resource-control incident. It reads the exact immutable resource-incident snapshot and current `resource-control.json`, then projects incident reason/time, counts of affected work and historical retained proxy leases, detection-time resource metrics, action outcomes, conclusion-file existence and current gate/survivor state. It refuses path-like IDs and identity-mismatched snapshots. For current backend and lease counts, pair it with `cointos-health --json`; use `cointos-job-info TASK_ID --json` for one exact worker. These summaries do not establish recovery safety; inspect specific underlying evidence before deciding on a transition. The live command has been checked against incident `20260925T162248Z-0` without changing the emergency gate.

The bounded in-memory summary test verifies that this projection never claims recovery safety.

Proof:

```bash
python3 -B -c 'from tests.test_incident_inspection import IncidentInspectionTests; IncidentInspectionTests("test_summary_is_bounded_and_never_claims_recovery").test_summary_is_bounded_and_never_claims_recovery()'
```
