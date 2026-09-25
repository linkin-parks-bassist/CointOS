---
status: green
revised_at: "2026-09-25T18:01:00+10:00"
---

The AMD-on-Wheels ingestion task was wanted and healthy, but its hand-built root `contact_requested` contract incorrectly supplied `maximum_output_bytes: 65536`, `run_seconds: 900`, `task_seconds: 1800`, and other finite execution ceilings. The first runner crossed 65,536 raw log bytes after reading the ingestion skill and source inventory. Output accounting includes serialized tool results, not only assistant prose, so the checkpoint occurred after only a small model response. The executor safely closed the runner and resumed the same OpenCode session. A later 900-second run ceiling caused another interruption.

This was neither cancellation nor resource pressure. Scope described a bounded batch, but that did not justify arbitrary lifetime slices. Generic task-contract validation had accepted the contradictory finite contact contract even though normal authenticated-contact constructors already emitted unlimited execution budgets.

`validate_task_contract` now normalizes the five execution-lifetime fields of every root `contact_requested` contract to `None` while preserving `maximum_children` as a delegation bound. Specialized authority profiles such as `bounded_maintenance` still retain explicit finite budgets. The live worker was closed once under dispatch-trigger isolation, its exact session was preserved, its durable contract and remaining budget were normalized, and it resumed with `deadline_monotonic: None`.

Evidence: source and installed `ecosystem/task_contracts.py` match and compile; 27 existing task-contract, intake, and control-turn tests pass; direct smoke checks prove root-contact normalization and preservation of specialized finite budgets.
