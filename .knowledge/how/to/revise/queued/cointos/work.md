---
status: green
revised_at: "2026-10-02T01:43:37+10:00"
---

Use `cointos hold PROJECT:ITEM` when you need to stop dispatch while deciding, then `cointos revise PROJECT:ITEM "COMPLETE BRIEF" --reason "WHY"`. Coin's `revise_item` uses the same API. The owning project's live manager or the user may revise work. The whole brief, including its dependency line, is replaced; omitted construction stage and reasoning effort are retained, and omitted budget limits remain unchanged. Explicit `--stage`, `--reasoning-effort` or generation-limit flags change only the requested metadata; supplied budget fields merge with the record's existing limits.

Revision queues the item again, clears the old blocker/hold and restarts an existing task on a fresh conversation while preserving its branch and files. It resets retry/rejection state for the new assignment. Earlier work is retained only where it still fits. Accepted or superseded items cannot be revised, and a worker currently under a running integration must wait until that integration ends. Run control and revision are separate: killing an integrator keeps its own task held until explicitly resumed.

`queues.contents` validates the candidate before mutation; `queues.revise` preserves omitted metadata and merges named budget limits; `lifecycle.revise` updates and restarts the task. This prevents a wording correction from changing test-contract or skeleton work into implementation work, with the wrong edit/landing policy. Queue and task metadata must agree after revision.

Evidence: `queues.py`, `lifecycle.py`, API/CLI/Coin controls and `tests/test_revision.py`, which checks preservation, explicit stage/effort changes, partial budgets and branch/session behavior. Live repair and metadata-preservation probes belong to `what/is/the/live/acceptance/evidence/for/cointos.md`.
