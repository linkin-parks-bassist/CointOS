---
status: green
revised_at: "2026-10-19T17:11:41+11:00"
---

The active runtime owns two scheduler settings that change without process replacement:

- `scheduler.slice_seconds`: how long an equal-priority holder keeps its turn.
- `scheduler.chunk_tokens`: the maximum generation tokens in one GPU step.

Change them through the dashboard Machine panel or `POST /api/scheduler` with either or both fields. The API validates the complete resulting pair and persists it before applying it. Direct edits to the active runtime's `config/cointos.json` are noticed each daemon tick. Editing source does not affect installed runtime.

`slice_seconds` must be finite and positive. `chunk_tokens` must be a positive integer, never a boolean. Invalid/partial configuration retains the last valid pair and exposes `config_error`. The ledger's `scheduler` object is the authority for effective values.

The installed scheduler counts reads and generation from admission; a reader yields to equals only with a reusable partial checkpoint. Existing turns retain their clocks. A shorter slice takes effect at a completed GPU step; no in-flight request is cut. Tool grace never extends past the slice end. Workers read `chunk_tokens` at step start: an in-flight step finishes at its old size, and the next uses the new value without losing tokens.

Current installed steps/slices are 96 tokens/60 seconds; source defaults remain 32/30. Preserve live user settings across compatible upgrades. Historically, at a 70k Qwen context under concurrent Coin load, 96-token steps reached about 25 seconds and triggered the existing 15-second overdue-preemption check; 32-token steps reduced that observed stall. This is not authority to reset the current pair. Verify waiting-agent progress and check recovery; token count cannot guarantee a wall-time bound.

Step size and slice are independent. Smaller steps improve pre-emption granularity but add transport, serialization, pending-token consumption and scheduling overhead. Actual switches can add snapshot costs. Measure the throughput trade-off under representative load; short benchmarks made with 96-token steps do not establish current live throughput.

No model shape or weight reload is required. Older installed code needs compatible installation before these fields reload. `how/to/restart/cointos.md` owns larger replacement choices.
