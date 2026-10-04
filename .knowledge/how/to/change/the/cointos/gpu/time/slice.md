---
status: green
revised_at: "2026-09-30T10:26:55+10:00"
---

The active runtime owns two scheduler settings that change without process replacement:

- `scheduler.slice_seconds`: how long an equal-priority generating holder keeps its turn.
- `scheduler.chunk_tokens`: the maximum generation tokens in one GPU step.

Change them through the dashboard Machine panel or `POST /api/scheduler` with either or both fields. The API validates the complete resulting pair and persists it before applying it. Direct edits to the active runtime's `config/cointos.json` are also noticed each daemon tick. Editing the source checkout does not affect the installed runtime.

`slice_seconds` must be finite and positive. `chunk_tokens` must be a positive integer and cannot be a boolean. Invalid or partially written configuration retains the last valid active pair and exposes `config_error` in the ledger/dashboard. The ledger's `scheduler` object is the authority for the effective values.

An existing turn keeps its original clock. A shorter slice can make its holder yield at the next completed GPU step; no in-flight backend request is cut. Tool-call grace never extends past the current slice end. A lane worker reads `chunk_tokens` at each step start, so an in-flight step finishes at its old size and the next step uses the new one without losing generated tokens.

Step size and time slice are independent. Smaller generation steps improve pre-emption granularity but add HTTP, serialization and scheduling overhead. More frequent actual switches may also add snapshot save/restore cost. The throughput trade-off must be measured under representative load; configuration alone does not establish it.

No model shape or weight reload is required. Older installed code needs one compatible live installation before these fields can reload; afterwards they are true live settings. `how/to/restart/cointos.md` owns larger replacement choices.
