---
status: green
revised_at: "2026-09-25T23:32:28+10:00"
---

`ecosystem status` scans `state/jobs/*.json`. Historical `task-*.opencode.json` files contain OpenCode provider configuration, not job state, and must be skipped. The installed status also counts kindless local audit records as jobs: their `ready` and `run_finished` states are not runnable managed work. After David authorized removal, the exact ten kindless `ready` local audit records were moved from `state/jobs` to the recoverable `state/archive/stale-kindless-ready-20260925/`; no real managed task was moved. Kindless `run_finished` audit records remain, so the installed flat count is still not a managed-work count. Source `cli.status` excludes sidecars and unknown/kindless records, retaining a flat count of recognized records and reporting `managed_agent_jobs` plus `by_kind`; this source fix awaits a drained deployment. Until then use installed `cointos-jobs --active` for actual managed tasks. Do not delete historical records merely to make a count appear clean.
