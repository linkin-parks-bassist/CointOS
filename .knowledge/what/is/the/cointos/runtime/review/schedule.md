---
status: green
revised_at: "2026-11-07T15:12:56+11:00"
---

The user requested a Steward every two hours to inspect the preceding four hours of CointOS logs/activity and dispatch a First Responder for concrete unowned problems. The overlapping lookback is intentional; existing recovery/work owners should prevent duplicate investigations. Routine findings stay internal.

The durable Coin wake is f7f0d80f96f74769b7af6ff8b234773d in ~/.CointOS/state/coin/wakes. Its schedule is `7 1-23/2 * * *` in Australia/Sydney: 01:07, 03:07 and subsequent odd local hours, following daylight saving. The agent is a Steward named cointos-runtime-review with standard/log tools. The first occurrence was requested immediately as system:cointos-runtime-review-1 and was verified running. Later occurrences start without a Coin model turn. Wakes survive restart; missed occurrences collapse and an active prior occurrence is retained rather than duplicated.

The brief checks Coin responsiveness/reachability, autonomous progress, workflow blockage, wasted GPU work and scheduling using timestamped runtime events, metrics and named task transcripts. A First Responder receives specific evidence and the affected assignment, or a standalone runtime diagnostic brief when no product assignment owns the issue. The Steward does not implement product fixes. Its checked receipt names a recovery_handoff or follows ordinary no_action review when healthy.

Source/installed support includes scheduled dispatch roles, per-occurrence replay/overlap handling, Steward-to-First-Responder dispatch, standalone runtime diagnoses and typed recovery handoffs. tests.test_scheduled_steward plus station/wake, completion, handoff and MCP tests pass (one native skip). Registration, the next local occurrence and actual first-run start were read back; a completed autonomous review and later natural firing still need observation. The private setup receipt is /tmp/cointos-scheduled-steward.json. This schedule is user-authorised; it is not a new general watcher subsystem.
