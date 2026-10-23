---
status: green
revised_at: "2026-10-23T20:50:27+11:00"
---

`Spawn scout` sits in the dashboard header beside Queue work and Run operator, left of the run switch. It calls `POST /api/scout` and reports the outcome in a toast ("Scout scheduled", "A scout is already scheduled" or the error), so no status text shifts the layout. It is disabled while a steward task is waiting or running, while CointOS is paused, or while its request is in flight; its tooltip says which. Source and installed copies are `web/dashboard.html` and `~/.CointOS/web/dashboard.html`.
