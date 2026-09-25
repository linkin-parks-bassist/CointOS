---
status: green
revised_at: "2026-09-26T08:11:40+10:00"
---

Incident `20260925T162248Z-0` no longer remains in emergency. Both the original Sole Survivor and its first replacement failed required-conclusion-artifact acceptance, leaving ordinary work halted. David explicitly requested a working system, and a narrowly gated operator recovery passed live resource health, lease reconciliation, durable gate smoke, and managed-dispatch start checks. Resource mode is now normal and the authoritative `state/workload-control.json` gate is open; `cointos-health` reads that live gate rather than the stale emergency snapshot field.

The deeper defect was a one-retry ceiling that turned a failed recovery worker into a sticky emergency requiring David to notice and intervene. The installed guard now schedules further dedicated survivor escalation after terminal failure when the incident record exists and resources are healthy. It preserves preceding retry records and uses an exponential delay capped at one hour. It does not silently reopen ordinary intake: the recovery worker still must diagnose, repair, and pass `resource-control recover` postconditions. The guard process was restarted with this code and the focused tests pass, but another live failed-survivor incident has not been exercised. The exact cause of the earlier workers' incomplete handoffs remains open.
