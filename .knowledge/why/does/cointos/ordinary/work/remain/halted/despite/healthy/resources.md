---
status: green
revised_at: "2026-09-26T08:01:52+10:00"
---

Ordinary work had remained halted despite healthy resources because the resource-control emergency state, not RAM headroom, governed dispatch. Both authorized Sole Survivor attempts failed required-artifact acceptance, leaving the work gate draining. David explicitly requested restoration. The narrowly gated failed-terminal-replacement operator recovery passed current resource health, lease reconciliation, durable gate smoke, and dispatch-start checks. The current resource mode is normal and `state/workload-control.json` reports the authoritative gate open. `cointos-health` now reads that gate directly rather than the stale emergency snapshot field.

Do not infer authority from apparent headroom, hand-edit runtime JSON, or spoof survivor identity. Recheck current health and durable gate before relying on this volatile operational state. The earlier September 25 halt caused by a stale worker lease and misrooted watchdog was separate.
